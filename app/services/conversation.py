import logging
import uuid
from sqlalchemy.orm import Session
from app.config import settings
from app.database import Contact, ConversationState, StudentProgress, StudentSession
from app.models.schemas import IncomingMessage
from app.services.gemini import GeminiService
from app.services.message_sender import MessageSender
from app.services.ocr import OCRService
from app.services.question_provider import question_provider

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
        
        msg_text = (message.text or "").lower().strip()
        
        saudacoes = ["oi", "ola", "olá", "bom dia", "boa tarde", "boa noite", "menu", "reset", "inicio", "opa"]
        if any(msg_text.startswith(s) for s in saudacoes):
            if session.state == ConversationState.AWAITING_TOPIC.value:
                await self._send_topic_menu(contact.phone)
            else:
                await self._send_welcome_message(contact.phone)
                session.state = ConversationState.AWAITING_TOPIC.value
                db.commit()
            return

        if session.state == ConversationState.AWAITING_CONTINUE.value and msg_text in self.YES_WORDS:
            sent = await self._send_next_question(db, contact, session)
            if not sent:
                session.state = ConversationState.AWAITING_REDO.value
                db.commit()
                await self.messages.send_text(contact.phone, settings.redo_topic_message)
            return

        if session.state == ConversationState.AWAITING_TOPIC.value:
            await self._handle_topic_selection(db, contact, session, message)
            return

        if session.state == ConversationState.AWAITING_ANSWER.value:
            await self._handle_answer(db, contact, session, message)
            return

        if session.state == ConversationState.AWAITING_CONTINUE.value:
            await self._handle_continue_decision(db, contact, session, message)
            return

        logger.info(f"Entrada '{msg_text}' não reconhecida.")
        await self._reset_to_topic_selection(db, session)

    def _get_or_create_contact(self, db: Session, message: IncomingMessage) -> Contact:
        contact = db.query(Contact).filter(Contact.phone == message.phone).one_or_none()
        if not contact:
            contact = Contact(phone=message.phone, name=message.contact_name or "Aluno")
            db.add(contact)
            db.commit()
            db.refresh(contact)
        return contact

    def _get_or_create_session(self, db: Session, contact: Contact) -> StudentSession:
        session = db.query(StudentSession).filter(StudentSession.contact_id == contact.id).one_or_none()
        if not session:
            session = StudentSession(
                contact_id=contact.id, 
                state=ConversationState.AWAITING_TOPIC.value
            )
            db.add(session)
            db.commit()
            db.refresh(session)
        return session

    async def _handle_answer(self, db: Session, contact: Contact, session: StudentSession, message: IncomingMessage) -> None:
        if not session.current_question_id:
            await self._reset_to_topic_selection(db, session)
            return
        
        answer_text = (message.text or "").strip()
        
        # Lógica de OCR ou texto simples...
        try:
            correction = await self.gemini.correct_answer(None, None, answer_text) # Exemplo simplificado
            feedback = correction.feedback
            
            db.add(StudentProgress(
                contact_id=contact.id, 
                topic=session.current_topic or "", 
                question_id=session.current_question_id, 
                question_name=session.current_question_name or "", 
                answer_text=answer_text, 
                feedback=feedback, 
                is_correct="yes" if correction.is_correct else "no"
            ))
            session.state = ConversationState.AWAITING_CONTINUE.value
            db.commit()
            
            await self.messages.send_text(contact.phone, f"*{feedback}*")
            
            img_path = await self.gemini.get_or_create_resolution_image(
                session.current_question_id, 
                session.current_question_name or "Questão"
            )
            if img_path:
                await self.messages.send_image(contact.phone, img_path)
            
            await self.messages.send_text(contact.phone, "Deseja continuar?")
        except Exception as e:
            logger.error(f"Erro no fluxo de resposta: {e}")
            await self.messages.send_text(contact.phone, "Erro ao processar.")

    # Adicione aqui os demais métodos que já existiam (_send_topic_menu, _handle_topic_selection, etc)
