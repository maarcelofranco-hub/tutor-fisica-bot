import logging
import uuid
from difflib import SequenceMatcher
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

    async def _send_welcome_message(self, phone: str) -> None:
        msg = "🍎 *Olá! Sou seu tutor de Física.*\n\nPara começarmos, digite o nome do tema que deseja estudar."
        await self.messages.send_text(phone, msg)
        await self._send_topic_menu(phone)

    async def _send_topic_menu(self, phone: str) -> None:
        temas = self.questions.list_topics()
        menu_organizado = {}
        for tema in temas:
            if "-" in tema:
                partes = tema.split("-", 1)
                area = partes[0].strip()
                nome_tema = partes[1].strip()
            else:
                area = "GERAL"
                nome_tema = tema
            if area not in menu_organizado:
                menu_organizado[area] = []
            menu_organizado[area].append(nome_tema)
        
        msg = "*Escolha um tema para começar:*\n"
        for area in sorted(menu_organizado.keys()):
            msg += f"\n*{area.upper()}*\n"
            for t in sorted(menu_organizado[area]):
                msg += f"- {t}\n"
        await self.messages.send_text(phone, msg)

    async def _handle_topic_selection(self, db: Session, contact: Contact, session: StudentSession, message: IncomingMessage) -> None:
        topic_input = (message.text or "").strip().lower()
        if not topic_input:
            await self._send_topic_menu(contact.phone)
            return
        topics = self.questions.list_topics()
        resolved_topic = None
        for t in topics:
            nome_limpo = t.split("-", 1)[-1].strip().lower()
            if nome_limpo == topic_input or t.lower() == topic_input or SequenceMatcher(None, nome_limpo, topic_input).ratio() > 0.8:
                resolved_topic = t
                break
        if resolved_topic:
            session.current_topic = resolved_topic
            sent = await self._send_next_question(db, contact, session)
            if not sent:
                await self.messages.send_text(contact.phone, "Este tema ainda não tem questões cadastradas.")
                await self._reset_to_topic_selection(db, session, send_menu=False)
        else:
            await self.messages.send_text(contact.phone, "Desculpe, não encontrei esse tema. Por favor, escolha um tema da lista abaixo:")
            await self._send_topic_menu(contact.phone)

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
            explanation = (correction.explanation or "").replace("\\n", "\n")
            db.add(StudentProgress(contact_id=contact.id, topic=session.current_topic or "", question_id=session.current_question_id, question_name=session.current_question_name or "", answer_text=answer_text, feedback=feedback, is_correct="yes" if correction.is_correct else "no"))
            session.state = ConversationState.AWAITING_CONTINUE.value
            db.commit()
            await self.messages.send_text(contact.phone, f"*{feedback}*\n\n*Resolução:*\n{explanation}")
            await self.messages.send_text(contact.phone, settings.continue_question_message)
        except Exception as e:
            logger.error(f"Erro: {e}")
            await self.messages.send_text(contact.phone, "Instabilidade. Aguarde um pouco.")

    async def _handle_continue_decision(self, db: Session, contact: Contact, session: StudentSession, message: IncomingMessage) -> None:
        decision = self._normalize_decision(message.text)
        if decision == "yes":
            if not await self._send_next_question(db, contact, session):
                session.state = ConversationState.AWAITING_REDO.value
                db.commit()
                await self.messages.send_text(contact.phone, settings.redo_topic_message)
            return
        await self._reset_to_topic_selection(db, session)

    async def _handle_redo_decision(self, db: Session, contact: Contact, session: StudentSession, message: IncomingMessage) -> None:
        if self._normalize_decision(message.text) == "yes":
            self._clear_topic_progress(db, contact.id, session.current_topic)
            if not await self._send_next_question(db, contact, session):
                await self.messages.send_text(contact.phone, "Sem questões.")
        await self._reset_to_topic_selection(db, session)

    def _clear_topic_progress(self, db: Session, contact_id: int, topic: str) -> None:
        db.query(StudentProgress).filter(StudentProgress.contact_id == contact_id, StudentProgress.topic == topic).delete()
        db.commit()

    async def _send_next_question(self, db: Session, contact: Contact, session: StudentSession) -> bool:
        topic = session.current_topic
        if not topic: return False
        answered_ids = {row.question_id for row in db.query(StudentProgress).filter(StudentProgress.contact_id == contact.id, StudentProgress.topic == topic)}
        next_question = next((q for q in self.questions.list_questions(topic) if q.id not in answered_ids), None)
        if not next_question: return False
        await self.messages.send_question_image(phone=contact.phone, caption=next_question.name, question_id=next_question.id)
        session.current_question_id = next_question.id
        session.current_question_name = next_question.name
        session.state = ConversationState.AWAITING_ANSWER.value
        db.commit()
        return True

    async def _reset_to_topic_selection(self, db: Session, session: StudentSession, send_menu: bool = True) -> None:
        session.state = ConversationState.AWAITING_TOPIC.value
        session.current_topic = None
        session.current_question_id = None
        session.current_question_name = None
        db.commit()
        if session.contact and send_menu:
            await self._send_topic_menu(session.contact.phone)

    def _get_or_create_contact(self, db: Session, message: IncomingMessage) -> Contact:
        from app.utils.phone import normalize_phone
        message.phone = normalize_phone(message.phone)
        contact = db.query(Contact).filter(Contact.phone == message.phone).one_or_none()
        if not contact:
            # CORREÇÃO: Criando o contato apenas com o 'phone', evitando o erro de 'display_name' que não existe no banco
            contact = Contact(phone=message.phone)
            db.add(contact)
            db.commit()
        return contact

    def _get_or_create_session(self, db: Session, contact: Contact) -> StudentSession:
        session = db.query(StudentSession).filter(StudentSession.contact_id == contact.id).one_or_none()
        if not session:
            session = StudentSession(contact_id=contact.id)
            db.add(session)
            db.commit()
        session.contact = contact
        return session

    def _normalize_decision(self, text: str | None) -> str | None:
        if not text: return None
        n = text.strip().lower()
        if n in self.YES_WORDS: return "yes"
        if n in self.NO_WORDS: return "no"
        return None

    def _looks_like_topic(self, text: str | None) -> bool:
        if not text: return False
        return any(labels_match(item, text) for item in self.questions.list_topics())

conversation_service = ConversationService()
