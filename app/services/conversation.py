import logging
import uuid
from difflib import SequenceMatcher
from sqlalchemy.orm import Session
from app.config import settings
from app.database import Contact, ConversationState, StudentProgress, StudentSession, QuestionResolution
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

        logger.info(f"Entrada '{msg_text}' não reconhecida. Enviando menu proativo.")
        await self._reset_to_topic_selection(db, session)

    # ... (Mantenha aqui os seus métodos _send_welcome_message, _send_topic_menu, _handle_topic_selection e outros) ...

    async def _handle_answer(self, db: Session, contact: Contact, session: StudentSession, message: IncomingMessage) -> None:
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
            await self.messages.send_text(contact.phone, "Não consegui ler sua resposta.")
            return

        question_bytes, question_mime = self.questions.get_question_image(session.current_question_id)
        
        try:
            correction = await self.gemini.correct_answer(question_bytes, question_mime, answer_text)
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
            
            # ENVIO DO FEEDBACK TEXTUAL
            await self.messages.send_text(contact.phone, f"*{feedback}*")
            
            # GERAÇÃO/ENVIO DA IMAGEM ELITE
            img_path = await self.gemini.get_or_create_resolution_image(
                session.current_question_id, 
                session.current_question_name or "Questão de Física"
            )
            if img_path:
                await self.messages.send_image(contact.phone, img_path)
            
            await self.messages.send_text(contact.phone, settings.continue_question_message)
            
        except Exception as e:
            logger.error(f"Erro no fluxo de resposta: {e}")
            await self.messages.send_text(contact.phone, "Instabilidade. Aguarde um pouco.")

    # ... (Mantenha o restante da classe abaixo) ...
