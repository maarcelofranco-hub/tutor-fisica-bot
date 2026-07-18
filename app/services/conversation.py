import logging
import uuid
from difflib import SequenceMatcher
from sqlalchemy.orm import Session
from app.config import settings
from app.database import Contact, ConversationState, StudentProgress, StudentSession
from app.models.schemas import IncomingMessage
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
            await self._send_welcome_message(contact.phone)
            session.state = ConversationState.AWAITING_TOPIC.value
            db.commit()
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

        logger.info(f"Entrada '{msg_text}' não reconhecida. Enviando menu proativo.")
        await self._reset_to_topic_selection(db, session)

    async def _send_welcome_message(self, phone: str) -> None:
        msg = (
            "🍎 *Olá! Sou seu tutor de Física.*\n\n"
            "Para começarmos, siga estes passos:\n"
            "1️⃣ Digite o nome do tema ou assunto que deseja estudar.\n"
            "2️⃣ Eu buscarei as melhores questões para você.\n"
            "3️⃣ Resolva e envie a resposta para correção imediata.\n\n"
            "Qual tema você quer estudar agora?"
        )
        await self.messages.send_text(phone, msg)
        await self._send_topic_menu(phone)

    async def _send_topic_menu(self, phone: str) -> None:
        temas = self.questions.list_topics()
        menu_organizado = {}
        for tema in temas:
            area = tema.split("-")[0].strip() if "-" in tema else "GERAL"
            nome = tema.split("-")[1].strip() if "-" in tema else tema
            if area not in menu_organizado: menu_organizado[area] = []
            menu_organizado[area].append(nome)
        
        msg = "*Escolha um tema para começar:*\n"
        for area in sorted(menu_organizado.keys()):
            msg += f"\n*{area.upper()}*\n"
            for t in sorted(menu_organizado[area]):
                msg += f"• {t}\n"
        await self.messages.send_text(phone, msg)

    async def _handle_topic_selection(self, db: Session, contact: Contact, session: StudentSession, message: IncomingMessage) -> None:
        topic_input = (message.text or "").strip().lower()
        topics = self.questions.list_topics()
        resolved_topic = next((t for t in topics if t.split("-")[-1].strip().lower() == topic_input), None)
        
        if resolved_topic:
            session.current_topic = resolved_topic
            session.state = ConversationState.AWAITING_ANSWER.value
            db.commit()
            await self._send_next_question(db, contact, session)
        else:
            await self.messages.send_text(contact.phone, "Desculpe, não encontrei esse tema. Por favor, escolha um tema da lista abaixo:")
            await self._send_topic_menu(contact.phone)

    async def _send_next_question(self, db: Session, contact: Contact, session: StudentSession) -> bool:
        # Mantém a sua lógica de buscar questão e enviar via media_id
        # ... (seu código de envio de imagem aqui) ...
        return True

    def _get_or_create_contact(self, db: Session, message: IncomingMessage) -> Contact:
        # AQUI FOI A CORREÇÃO: Removido 'name=message.contact_name' para evitar o erro do banco
        contact = db.query(Contact).filter(Contact.phone == message.phone).one_or_none()
        if not contact:
            contact = Contact(phone=message.phone)
            db.add(contact)
            db.commit()
        return contact

    def _get_or_create_session(self, db: Session, contact: Contact) -> StudentSession:
        session = db.query(StudentSession).filter(StudentSession.contact_id == contact.id).one_or_none()
        if not session:
            session = StudentSession(contact_id=contact.id, state=ConversationState.AWAITING_TOPIC.value)
            db.add(session)
            db.commit()
        return session

    def _reset_to_topic_selection(self, db: Session, session: StudentSession) -> None:
        session.state = ConversationState.AWAITING_TOPIC.value
        db.commit()
        if session.contact:
            self._send_topic_menu(session.contact.phone)

    def _looks_like_topic(self, text: str | None) -> bool:
        if not text: return False
        return any(labels_match(item, text) for item in self.questions.list_topics())
