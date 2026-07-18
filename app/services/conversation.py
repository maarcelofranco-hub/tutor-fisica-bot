import logging
import uuid
from sqlalchemy.orm import Session
from app.database import Contact, ConversationState, StudentSession
from app.models.schemas import IncomingMessage
from app.services.message_sender import MessageSender
from app.services.gemini import GeminiService
from app.services.ocr import OCRService
from app.services.question_provider import question_provider

logger = logging.getLogger(__name__)

class ConversationService:
    def __init__(self) -> None:
        self.messages = MessageSender()
        self.gemini = GeminiService()
        self.ocr = OCRService(self.gemini)
        self.questions = question_provider

    async def handle_message(self, db: Session, message: IncomingMessage) -> None:
        contact = self._get_or_create_contact(db, message)
        session = self._get_or_create_session(db, contact)
        
        msg_text = (message.text or "").lower().strip()

        # 1. Fluxo de Boas-vindas (Os passos 1, 2, 3)
        if any(s in msg_text for s in ["oi", "ola", "olá", "inicio", "menu"]):
            await self._send_welcome_message(contact.phone)
            session.state = ConversationState.AWAITING_TOPIC.value
            db.commit()
            return

        # 2. Fluxo de Escolha de Tema
        if session.state == ConversationState.AWAITING_TOPIC.value:
            if not self.questions.is_valid_topic(msg_text):
                await self.messages.send_text(contact.phone, "Tema não encontrado. Escolha um dos disponíveis.")
                await self._send_topic_menu(contact.phone)
            else:
                session.current_topic = msg_text
                session.state = ConversationState.AWAITING_ANSWER.value
                # Aqui o bot buscará a questão e enviará com o media_id pronto
                await self._send_next_question(db, contact, session)
            db.commit()
            return

        # (Manter aqui a lógica original de handle_answer, etc.)
        logger.info(f"Processando mensagem de {contact.phone}: {msg_text}")

    async def _send_welcome_message(self, phone: str):
        msg = (
            "Olá! Sou seu tutor de Física.\n\n"
            "Para começarmos, siga estes passos:\n"
            "1️⃣ Digite o nome do tema ou assunto que deseja estudar.\n"
            "2️⃣ Eu buscarei as melhores questões para você.\n"
            "3️⃣ Resolva e envie a resposta para correção imediata.\n\n"
            "Qual tema você quer estudar agora?"
        )
        await self.messages.send_text(phone, msg)

    async def _send_topic_menu(self, phone: str):
        topics = ", ".join(self.questions.list_topics())
        await self.messages.send_text(phone, f"Temas disponíveis: {topics}")

    def _get_or_create_contact(self, db: Session, message: IncomingMessage) -> Contact:
        contact = db.query(Contact).filter(Contact.phone == message.phone).one_or_none()
        if not contact:
            # Correção fundamental: Criar apenas com phone, sem 'name'
            contact = Contact(phone=message.phone)
            db.add(contact)
            db.commit()
            db.refresh(contact)
        return contact

    def _get_or_create_session(self, db: Session, contact: Contact) -> StudentSession:
        session = db.query(StudentSession).filter(StudentSession.contact_id == contact.id).one_or_none()
        if not session:
            session = StudentSession(contact_id=contact.id, state=ConversationState.AWAITING_TOPIC.value)
            db.add(session)
            db.commit()
            db.refresh(session)
        return session
