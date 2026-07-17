import logging
import uuid

from sqlalchemy.orm import Session

from app.config import settings
from app.database import Contact, ConversationState, StudentProgress, StudentSession
from app.models.schemas import IncomingMessage, Question
from app.services.gemini import GeminiService
from app.services.message_sender import MessageSender
from app.services.ocr import OCRService
from app.services.question_provider import question_provider
from app.utils.text import labels_match

logger = logging.getLogger(__name__)


class ConversationService:
    YES_WORDS = {"sim", "s", "yes", "quero", "continuar", "outra", "mais"}
    NO_WORDS = {"nao", "não", "n", "no", "parar", "stop", "outro tema", "trocar"}

    def __init__(self) -> None:
        self.messages = MessageSender()
        self.gemini = GeminiService()
        self.ocr = OCRService(self.gemini)
        self.questions = question_provider

    async def handle_message(self, db: Session, message: IncomingMessage) -> None:
        if not message.message_id:
            message.message_id = str(uuid.uuid4())

        contact = self._get_or_create_contact(db, message)
        session = self._get_or_create_session(db, contact)
        logger.info(
            "IN  [%s] state=%s text=%s",
            contact.phone,
            session.state,
            (message.text or "")[:120],
        )

        if session.state == ConversationState.AWAITING_TOPIC.value:
            await self._handle_topic_selection(db, contact, session, message)
            return

        if session.state == ConversationState.AWAITING_ANSWER.value:
            if self._looks_like_topic(message.text):
                await self._reset_to_topic_selection(db, session)
                await self._handle_topic_selection(db, contact, session, message)
                return
            await self._handle_answer(db, contact, session, message)
            return

        if session.state == ConversationState.AWAITING_CONTINUE.value:
            if self._looks_like_topic(message.text):
                await self._reset_to_topic_selection(db, session)
                await self._handle_topic_selection(db, contact, session, message)
                return
            await self._handle_continue_decision(db, contact, session, message)
            return

        if session.state == ConversationState.AWAITING_REDO.value:
            if self._looks_like_topic(message.text):
                await self._reset_to_topic_selection(db, session)
                await self._handle_topic_selection(db, contact, session, message)
                return
            await self._handle_redo_decision(db, contact, session, message)
            return

        await self._reset_to_topic_selection(db, session)

    async def _handle_topic_selection(
        self,
        db: Session,
        contact: Contact,
        session: StudentSession,
        message: IncomingMessage,
    ) -> None:
        topic = (message.text or "").strip()
        if not topic:
            await self._send_topic_menu(contact.phone)
            return

        self.questions.refresh()
        topics = self.questions.list_topics()
        if topics and not self.questions.topic_exists(topic):
            await self.messages.send_text(
                contact.phone,
                f"Tema nao encontrado. Temas disponiveis: {', '.join(topics)}",
            )
            await self._send_topic_menu(contact.phone, send_welcome=False)
            return

        resolved_topic = self.questions.resolve_topic_name(topic)
        session.current_topic = resolved_topic
        sent = await self._send_next_question(db, contact, session)
        if not sent:
            await self.messages.send_text(
                contact.phone,
                "Este tema ainda nao tem questoes cadastradas. Escolha outro tema ou aguarde novas imagens.",
            )
            await self._reset_to_topic_selection(db, session, send_menu=False)

    async def _handle_answer(
        self,
        db: Session,
        contact: Contact,
        session: StudentSession,
        message: IncomingMessage,
    ) -> None:
        if not session.current_question_id:
            await self._reset_to_topic_selection(db, session)
            return

        answer_text = (message.text or "").strip()
        if message.image_bytes:
            answer_text = await self.ocr.extract_text(message.image_bytes, message.media_mime_type or "image/png")
        elif message.media_id:
            media_bytes, media_mime = await self.messages.download_media(message.media_id)
            answer_text = await self.ocr.extract_text(media_bytes, media_mime)

        if not answer_text:
            await self.messages.send_text(
                contact.phone,
                "Nao consegui ler sua resposta. Envie novamente por texto ou foto mais nitida.",
            )
            return

        question_bytes, question_mime = self.questions.get_question_image(session.current_question_id)
        correction = await self.gemini.correct_answer(
            question_image_bytes=question_bytes,
            question_mime_type=question_mime,
            student_answer=answer_text,
        )

        feedback = correction.feedback
        explanation = correction.explanation or ""

        db.add(
            StudentProgress(
                contact_id=contact.id,
                topic=session.current_topic or "",
                question_id=session.current_question_id,
                question_name=session.current_question_name or "",
                answer_text=answer_text,
                feedback=feedback,
                is_correct="yes" if correction.is_correct else "no",
            )
        )
        session.state = ConversationState.AWAITING_CONTINUE.value
        db.commit()

        # Envia feedback + explicação formatada
        full_message = f"{feedback}"
        if explanation:
            full_message += f"\n\n{explanation}"
            
        await self.messages.send_text(contact.phone, full_message)
        await self.messages.send_text(contact.phone, settings.continue_question_message)

    async def _handle_continue_decision(
        self,
        db: Session,
        contact: Contact,
        session: StudentSession,
        message: IncomingMessage,
    ) -> None:
        decision = self._normalize_decision(message.text)
        if decision is None:
            await self.messages.send_text(
                contact.phone,
                "Responda com 'sim' para outra questao ou 'nao' para escolher outro tema.",
            )
            return

        if decision == "yes":
            sent = await self._send_next_question(db, contact, session)
            if not sent:
                session.state = ConversationState.AWAITING_REDO.value
                db.commit()
                await self.messages.send_text(contact.phone, settings.redo_topic_message)
            return

        await self._reset_to_topic_selection(db, session)

    async def _handle_redo_decision(
        self,
        db: Session,
        contact: Contact,
        session: StudentSession,
        message: IncomingMessage,
    ) -> None:
        decision = self._normalize_decision(message.text)
        if decision is None:
            await self.messages.send_text(
                contact.phone,
                "Responda com 'sim' para refazer este tema ou 'nao' para escolher outro tema.",
            )
            return

        if decision == "yes":
            topic = session.current_topic
            if not topic:
                await self._reset_to_topic_selection(db, session)
                return
            self._clear_topic_progress(db, contact.id, topic)
            sent = await self._send_next_question(db, contact, session)
            if not sent:
                await self.messages.send_text(
                    contact.phone,
                    "Este tema ainda nao tem questoes cadastradas. Escolha outro tema.",
                )
                await self._reset_to_topic_selection(db, session, send_menu=False)
            return

        await self.messages.send_text(contact.phone, settings.topic_completed_message)
        await self._reset_to_topic_selection(db, session)

    def _clear_topic_progress(self, db: Session, contact_id: int, topic: str) -> None:
        db.query(StudentProgress).filter(
            StudentProgress.contact_id == contact_id,
            StudentProgress.topic == topic,
        ).delete()
        db.commit()

    async def _send_next_question(self, db: Session, contact: Contact, session: StudentSession) -> bool:
        topic = session.current_topic
        if not topic:
            return False

        self.questions.refresh()
        answered_ids = {
            row.question_id
            for row in db.query(StudentProgress).filter(
                StudentProgress.contact_id == contact.id,
                StudentProgress.topic == topic,
            )
        }
        next_question = next(
            (q for q in self.questions.list_questions(topic) if q.id not in answered_ids),
            None,
        )
        if not next_question:
            return False

        await self._send_question(contact.phone, next_question)
        session.current_question_id = next_question.id
        session.current_question_name = next_question.name
        session.state = ConversationState.AWAITING_ANSWER.value
        db.commit()
        return True

    async def _send_question(self, phone: str, question: Question) -> None:
        image_bytes, mime_type = self.questions.get_question_image(question.id)
        await self.messages.send_question_image(
            phone=phone,
            image_bytes=image_bytes,
            mime_type=mime_type,
            caption=question.name,
        )

    async def _send_topic_menu(self, phone: str, send_welcome: bool = True) -> None:
        sent_menu = await self.messages.send_themes_menu(phone)
        if send_welcome:
            await self.messages.send_text(phone, settings.welcome_message)
        if not sent_menu:
            topics = self.questions.list_topics()
            if topics:
                await self.messages.send_text(
                    phone,
                    f"Temas disponiveis: {', '.join(topics)}",
                )

    async def _reset_to_topic_selection(
        self,
        db: Session,
        session: StudentSession,
        send_menu: bool = True,
    ) -> None:
        session.state = ConversationState.AWAITING_TOPIC.value
        session.current_topic = None
        session.current_question_id = None
        session.current_question_name = None
        db.commit()
        contact = session.contact
        if contact and send_menu:
            self.questions.refresh()
            await self._send_topic_menu(contact.phone)

    def _get_or_create_contact(self, db: Session, message: IncomingMessage) -> Contact:
        from app.utils.phone import normalize_phone

        message.phone = normalize_phone(message.phone)
        contact = db.query(Contact).filter(Contact.phone == message.phone).one_or_none()
        if contact:
            if message.contact_name and not contact.display_name:
                contact.display_name = message.contact_name
            return contact

        contact = Contact(phone=message.phone, display_name=message.contact_name)
        db.add(contact)
        db.commit()
        db.refresh(contact)

        session = StudentSession(contact_id=contact.id)
        db.add(session)
        db.commit()
        return contact

    def _get_or_create_session(self, db: Session, contact: Contact) -> StudentSession:
        session = db.query(StudentSession).filter(StudentSession.contact_id == contact.id).one_or_none()
        if session:
            session.contact = contact
            return session

        session = StudentSession(contact_id=contact.id)
        db.add(session)
        db.commit()
        db.refresh(session)
        session.contact = contact
        return session

    def _normalize_decision(self, text: str | None) -> str | None:
        if not text:
            return None
        normalized = text.strip().lower()
        if normalized in self.YES_WORDS:
            return "yes"
        if normalized in self.NO_WORDS:
            return "no"
        return None

    def _looks_like_topic(self, text: str | None) -> bool:
        if not text:
            return False
        self.questions.refresh()
        topics = self.questions.list_topics()
        return any(labels_match(item, text) for item in topics)


conversation_service = ConversationService()
