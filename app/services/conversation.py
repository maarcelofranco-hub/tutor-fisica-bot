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
            # Lógica simples de boas-vindas
            await self.messages.send_text(contact.phone, "Olá! Sou seu tutor de Física. Como posso ajudar hoje?")
            session.state = ConversationState.AWAITING_TOPIC.value
            db.commit()
            return

        # (Aqui continuam seus métodos de fluxo de estado)
        if session.state == ConversationState.AWAITING_TOPIC.value:
            await self.messages.send_text(contact.phone, "Por favor, escolha um tema.")
            return

        logger.info(f"Entrada '{msg_text}' processada para contato {contact.phone}")

    def _get_or_create_contact(self, db: Session, message: IncomingMessage) -> Contact:
        contact = db.query(Contact).filter(Contact.phone == message.phone).one_or_none()
        if not contact:
            # Removido o argumento 'name' que estava causando erro
            contact = Contact(phone=message.phone) 
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
