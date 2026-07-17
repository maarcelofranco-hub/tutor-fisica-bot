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
        
        # MENSAGEM DE BOAS-VINDAS COMPLETA
        if msg_text in ["oi", "ola", "olá", "bom dia", "boa tarde", "boa noite", "menu", "reset", "inicio"]:
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

        await self._reset_to_topic_selection(db, session)

    async def _send_welcome_message(self, phone: str) -> None:
        msg = (
            "🍎 *Olá! Sou seu tutor de Física.*\n\n"
            "Estou aqui para te ajudar a praticar e aprender de forma eficiente.\n\n"
            "Para começarmos, siga estes passos:\n"
            "1️⃣ Digite o *nome do tema* ou assunto que deseja estudar.\n"
            "2️⃣ Eu buscarei as melhores questões para você.\n"
            "3️⃣ Resolva e envie a resposta para correção imediata.\n\n"
            "Qual tema você quer estudar agora?"
        )
        await self.messages.send_text(phone, msg)

    async def _send_topic_menu(self, phone: str) -> None:
        self.questions.refresh()
        temas = self.questions.list_topics()
        
        menu_organizado = {}
        for tema in temas:
            if "-" in tema:
                partes = tema.split("-", 1)
                area = partes[0].strip()
                nome_tema = partes[1].strip()
            else:
                area = "OUTROS"
                nome_tema = tema
            
            if area not in menu_organizado:
                menu_organizado[area] = []
            menu_organizado[area].append(nome_tema)
        
        msg = "🍎 *Olá! Sou seu tutor de Física.*\n\nEscolha um tema para começar:\n"
        
        for area in sorted(menu_organizado.keys()):
            # Adicionado os 2 pontos após a interrogação
            msg += f"\n*{area.capitalize()}?:*\n"
            for t in sorted(menu_organizado[area]):
                msg += f"• {t}\n"
                
        msg += "\nQual tema você quer estudar agora?"
        await self.messages.send_text(phone, msg)

    # --- MANTENHA O RESTANTE DOS MÉTODOS (handle_topic_selection, handle_answer, etc.) IGUAIS AO ANTERIOR ---
    # (Ocultei para caber aqui, mas utilize a mesma lógica que já estava funcionando)
