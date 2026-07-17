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
from app.services.llm import selecionar_tema_por_input

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
        if msg_text in ["oi", "ola", "olá", "bom dia", "boa tarde", "boa noite", "menu", "reset", "inicio"]:
            await self._reset_to_topic_selection(db, session)
            return

        # --- A JUSTE AQUI: Se for Sim no estado de continuação, força a próxima questão ---
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
            if self._looks_like_topic(message.text):
                await self._reset_to_topic_selection(db, session)
                await self._handle_topic_selection(db, contact, session, message)
                return
            await self._handle_answer(db, contact, session, message)
            return

        if session.state == ConversationState.AWAITING_CONTINUE.value:
            await self._handle_continue_decision(db, contact, session, message)
            return

        if session.state == ConversationState.AWAITING_REDO.value:
            await self._handle_redo_decision(db, contact, session, message)
            return

        await self._reset_to_topic_selection(db, session)

    # ... (Mantenha os métodos _handle_topic_selection, _handle_answer, etc. abaixo exatamente como você já tinha)
    # A única alteração necessária foi no handle_message para priorizar a continuação do fluxo.
