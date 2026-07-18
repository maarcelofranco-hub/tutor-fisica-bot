import logging
from app.services.message_sender import MessageSender

logger = logging.getLogger(__name__)

async def handle_message(data: dict, sender: MessageSender):
    logger.info("Iniciando processamento da mensagem...")
    
    try:
        # Extrai os dados básicos da mensagem recebida da Meta
        entry = data.get("entry", [])
        if not entry: return
        
        changes = entry[0].get("changes", [])
        if not changes: return
        
        value = changes[0].get("value", {})
        messages = value.get("messages", [])
        
        if not messages: return
        
        message = messages[0]
        phone = message.get("from")
        text = message.get("text", {}).get("body", "").lower()
        
        logger.info(f"Texto recebido: {text}")

        # Lógica de resposta
        if "olá" in text or "oi" in text:
            await sender.send_text(phone, "Olá! Sou seu tutor de Física. Digite o nome do tema para começar.")
        else:
            # Caso não seja saudação, tenta mostrar o menu de temas
            success = await sender.send_themes_menu(phone)
            if not success:
                await sender.send_text(phone, "Não entendi. Digite um tema de física para começar.")
        
        logger.info("Mensagem processada com sucesso.")
            
    except Exception as e:
        logger.error(f"Erro ao processar mensagem no handler: {e}")
