import logging
from app.services.conversation import conversation_service
from app.models.schemas import IncomingMessage
from app.database import get_db

logger = logging.getLogger(__name__)

# Mantemos o 'sender' na assinatura apenas para não quebrar o webhook, 
# mas todo o envio será feito pelo conversation_service agora!
async def handle_message(data: dict, sender=None):
    try:
        # 1. Extração segura de dados para não dar "list index out of range"
        entry = data.get("entry", [])
        if not entry: return
        
        changes = entry[0].get("changes", [])
        if not changes: return
        
        value = changes[0].get("value", {})
        messages = value.get("messages", [])
        
        if not messages: return 
        
        message_data = messages[0]
        phone = message_data.get("from")
        text_raw = message_data.get("text", {}).get("body", "")
        message_id = message_data.get("id")
        
        # Extrair nome do contato
        contacts = value.get("contacts", [])
        contact_name = contacts[0].get("profile", {}).get("name") if contacts else ""
        
        # Extrair mídia caso o aluno mande foto da resolução (isso garante que a correção via imagem funcione!)
        media_id = None
        media_mime_type = None
        
        if "image" in message_data:
            media_id = message_data["image"].get("id")
            media_mime_type = message_data["image"].get("mime_type")
        elif "document" in message_data:
            media_id = message_data["document"].get("id")
            media_mime_type = message_data["document"].get("mime_type")
            
        logger.info("Encaminhando mensagem de %s para o ConversationService: '%s'", phone, text_raw)

        # 2. Monta o formato exato que o seu conversation.py exige
        incoming_msg = IncomingMessage(
            phone=phone,
            text=text_raw,
            contact_name=contact_name,
            message_id=message_id,
            media_id=media_id,
            media_mime_type=media_mime_type
        )
        
        # 3. Conecta no banco e PASSA A BOLA para o verdadeiro cérebro do bot
        db_generator = get_db()
        db = next(db_generator)
        try:
            await conversation_service.handle_message(db, incoming_msg)
        finally:
            db.close()
            
    except Exception as e:
        logger.error("Erro crítico no handler: %s", e)
