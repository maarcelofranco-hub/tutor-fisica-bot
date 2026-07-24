import logging
import uuid
import unicodedata
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
            
        # NOVA ROTA: Aguardando se o aluno quer a próxima questão ou tem dúvida
        if session.state == "AWAITING_NEXT_ACTION":
            await self._handle_next_action(db, contact, session, message)
            return

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
        
        def normalize(text):
            return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn').lower()
        
        normalized_input = normalize(topic_input)
        topics = self.questions.list_topics()
        
        resolved_topic = next((t for t in topics if normalize(t.split("-")[-1].strip()) == normalized_input), None)
        
        if resolved_topic:
            session.current_topic = resolved_topic
            session.state = ConversationState.AWAITING_ANSWER.value
            db.commit()
            await self._send_next_question(db, contact, session)
        else:
            await self.messages.send_text(contact.phone, "Tema não encontrado. Escolha um da lista.")
            await self._send_topic_menu(contact.phone)

    async def _handle_answer(self, db: Session, contact: Contact, session: StudentSession, message: IncomingMessage) -> None:
        if not session.current_question_id:
            await self._reset_to_topic_selection(db, session)
            return
        
        try:
            # 1. Envia a foto da resolução oficial IMEDIATAMENTE (Sem Gemini)
            await self.messages.send_resolution_image(
                phone=contact.phone, 
                question_id=session.current_question_id
            )
            
            # 2. Envia o menu perguntando o próximo passo (Sintaxe segura em aspas triplas)
            menu_text = """📝 *Resolução Oficial:*

O que deseja fazer agora?
👉 Digite *sim* para a próxima questão
👉 Envie *dúvidas* para uma explicação detalhada"""
            await self.messages.send_text(contact.phone, menu_text)

            # 3. Salva o progresso para não repetir a questão
            progress = StudentProgress(
                contact_id=contact.id,
                topic=session.current_topic,
                question_id=session.current_question_id,
                is_correct=True
            )
            db.add(progress)

            # 4. Muda o estado para aguardar a decisão ("sim" ou "dúvida")
            session.state = "AWAITING_NEXT_ACTION"
            db.commit()
                
        except Exception as e:
            logger.error(f"Erro ao processar resposta: {e}")
            await self.messages.send_text(contact.phone, "Ocorreu um erro ao buscar a resolução. Tente novamente.")

    async def _handle_next_action(self, db: Session, contact: Contact, session: StudentSession, message: IncomingMessage) -> None:
        texto = (message.text or "").strip().lower()
        
        # Se o aluno quiser avançar
        if texto in ["sim", "s", "proxima", "próxima"]:
            success = await self._send_next_question(db, contact, session)
            if not success:
                await self.messages.send_text(contact.phone, "Parabéns! Você completou todas as questões deste tema.")
                await self._reset_to_topic_selection(db, session)
                
        # Se o aluno tiver dúvidas (AQUI ACIONA O GEMINI)
        elif "duvida" in texto or "dúvida" in texto or "duvidas" in texto:
            await self.messages.send_text(contact.phone, "Certo! O professor IA está analisando a questão para te explicar...")
            try:
                # Aciona o Gemini para processar a dúvida sobre a questão atual
                analise_texto = await self.ocr.process_answer(message, session.current_question_id)
                await self.messages.send_text(contact.phone, analise_texto)
            except Exception as e:
                logger.error(f"Erro no Gemini: {e}")
                await self.messages.send_text(contact.phone, "Tive um problema ao processar sua dúvida.")
            
            # Repete a pergunta para ele não ficar preso
            await self.messages.send_text(contact.phone, "👉 Digite *sim* para ir para a próxima questão.")
            
        else:
            await self.messages.send_text(contact.phone, "Não entendi. Digite *sim* para a próxima questão ou *dúvidas* para uma explicação.")

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

    def _get_or_create_contact(self, db: Session, message: IncomingMessage) -> Contact:
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
