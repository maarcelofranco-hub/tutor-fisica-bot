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
# IMPORTANTE: Adicione esta linha abaixo para a busca inteligente funcionar
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
        topic_input = (message.text or "").strip()
        
        if not topic_input:
            await self._send_topic_menu(contact.phone)
            return

        self.questions.refresh()
        topics = self.questions.list_topics()

        # Tenta match exato ou usa a Busca Inteligente do Gemini
        if self.questions.topic_exists(topic_input):
            resolved_topic = self.questions.resolve_topic_name(topic_input)
        else:
            tema_sugerido = selecionar_tema_por_input(topic_input, topics)
            
            if tema_sugerido in topics:
                resolved_topic = tema_sugerido
            else:
                await self.messages.send_text(contact.phone, tema_sugerido)
                return

        session.current_topic = resolved_topic
        sent = await self._send_next_question(db, contact, session)
        if not sent:
            await self.messages.send_text(
                contact.phone,
                "Este tema ainda não tem questões cadastradas. Escolha outro tema.",
            )
            await self._reset_to_topic_selection(db, session, send_menu=False)

    async def _handle_answer(self, db: Session, contact: Contact, session: StudentSession, message: IncomingMessage) -> None:
        # ... (seu código original de correção permanece aqui)
        pass

    # ... (mantenha o restante dos métodos originais da sua classe inalterados)
