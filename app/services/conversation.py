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
        
        # Comandos de reset/saudação
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

        # MENU PROATIVO: Se nada for reconhecido, envia o menu e reseta o estado
        logger.info(f"Entrada '{msg_text}' não reconhecida. Enviando menu proativo.")
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
                
        msg += "\nQual tema você quer estudar agora?"
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
            await self.messages.send_text(contact.phone, "Não encontrei um tema relacionado ao que você digitou.")
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
            await self.messages.send_text(contact.phone, "Não consegui ler sua resposta. Envie novamente por texto ou foto mais nítida.")
            return

        question_bytes, question_mime = self.questions.get_question_image(session.current_question_id)
        
        try:
            correction = await self.gemini.correct_answer(
                question_image_bytes=question_bytes, 
                question_mime_type=question_mime, 
                student_answer=answer_text
            )
            
            feedback = correction.feedback
            explanation = (correction.explanation or "").replace("\\n", "\n")
            
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
            
            full_message = f"*{feedback}*"
            if explanation:
                full_message += f"\n\n*Resolução:*\n{explanation}"
                
            await self.messages.send_text(contact.phone, full_message)
            await self.messages.send_text(contact.phone, settings.continue_question_message)
            
        except Exception as e:
            logger.error(f"Erro ao processar correção: {e}")
            await self.messages.send_text(
                contact.phone, 
                "Estou com uma instabilidade momentânea na correção. Por favor, aguarde uns 60 segundos e reenvie sua resposta."
            )

    async def _handle_continue_decision(self, db: Session, contact: Contact, session: StudentSession, message: IncomingMessage) -> None:
        decision = self._normalize_decision(message.text)
        if decision is None:
            await self.messages.send_text(contact.phone, "Responda com 'sim' para outra questão ou 'nao' para escolher outro tema.")
            return
        if decision == "yes":
            sent = await self._send_next_question(db, contact, session)
            if not sent:
                session.state = ConversationState.AWAITING_REDO.value
                db.commit()
                await self.messages.send_text(contact.phone, settings.redo_topic_message)
            return
        await self._reset_to_topic_selection(db, session)

    async def _handle_redo_decision(self, db: Session, contact: Contact, session: StudentSession, message: IncomingMessage) -> None:
        decision = self._normalize_decision(message.text)
        if decision is None:
            await self.messages.send_text(contact.phone, "Responda com 'sim' para refazer este tema ou 'nao' para escolher outro tema.")
            return
        if decision == "yes":
            topic = session.current_topic
            if not topic:
                await self._reset_to_topic_selection(db, session)
                return
            self._clear_topic_progress(db, contact.id, topic)
            sent = await self._send_next_question(db, contact, session)
            if not sent:
                await self.messages.send_text(contact.phone, "Este tema ainda não tem questões cadastradas.")
                await self._reset_to_topic_selection(db, session, send_menu=False)
            return
        await self.messages.send_text(contact.phone, settings.topic_completed_message)
        await self._reset_to_topic_selection(db, session
