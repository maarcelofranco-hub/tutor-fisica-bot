import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import Contact, StudentProgress, StudentSession, get_db
from app.models.schemas import (
    IncomingMessage,
    OutboundMessageResponse,
    SessionResponse,
    TestMessageRequest,
    TopicsResponse,
)
from app.services.conversation import conversation_service
from app.services.outbox import outbox
from app.services.question_provider import question_provider

router = APIRouter(prefix="/test", tags=["test"])


@router.get("/topics", response_model=TopicsResponse)
def list_topics():
    return TopicsResponse(topics=question_provider.list_topics())


@router.post("/message")
async def send_test_message(payload: TestMessageRequest, db: Session = Depends(get_db)):
    outbox.clear(payload.phone)
    message = IncomingMessage(
        phone=payload.phone,
        message_id=str(uuid.uuid4()),
        text=payload.text,
        contact_name=payload.contact_name,
    )
    await conversation_service.handle_message(db, message)
    replies = outbox.get_messages(payload.phone)
    return {
        "phone": payload.phone,
        "replies": [
            OutboundMessageResponse(
                type=item.type,
                content=item.content,
                image_name=item.image_name,
            )
            for item in replies
        ],
    }


@router.get("/outbox/{phone}", response_model=list[OutboundMessageResponse])
def get_outbox(phone: str, clear: bool = False):
    return [
        OutboundMessageResponse(type=item.type, content=item.content, image_name=item.image_name)
        for item in outbox.get_messages(phone, clear=clear)
    ]


@router.get("/session/{phone}", response_model=SessionResponse)
def get_session(phone: str, db: Session = Depends(get_db)):
    contact = db.query(Contact).filter(Contact.phone == phone).one_or_none()
    if not contact:
        return SessionResponse(phone=phone, state="new")

    session = db.query(StudentSession).filter(StudentSession.contact_id == contact.id).one_or_none()
    answered = (
        db.query(StudentProgress).filter(StudentProgress.contact_id == contact.id).count()
        if contact
        else 0
    )
    if not session:
        return SessionResponse(phone=phone, state="new", answered_count=answered)

    return SessionResponse(
        phone=phone,
        state=session.state,
        current_topic=session.current_topic,
        current_question_name=session.current_question_name,
        answered_count=answered,
    )


@router.post("/reset/{phone}")
def reset_student(phone: str, db: Session = Depends(get_db)):
    contact = db.query(Contact).filter(Contact.phone == phone).one_or_none()
    if not contact:
        return {"status": "not_found"}

    db.query(StudentProgress).filter(StudentProgress.contact_id == contact.id).delete()
    session = db.query(StudentSession).filter(StudentSession.contact_id == contact.id).one_or_none()
    if session:
        session.state = "awaiting_topic"
        session.current_topic = None
        session.current_question_id = None
        session.current_question_name = None
    outbox.clear(phone)
    db.commit()
    return {"status": "reset"}
