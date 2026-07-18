import logging
import unicodedata
from app.services.message_sender import MessageSender

logger = logging.getLogger(__name__)

def normalizar_texto(texto: str) -> str:
    """Remove acentos e converte para minúsculas."""
    texto = texto.lower()
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

async def handle_message(data: dict, sender: MessageSender):
    try:
        # 1. Validação de segurança: verifica se existem dados de mensagem
        entry = data.get("entry", [])
        if not entry: return
        
        changes = entry[0].get("changes", [])
        if not changes: return
        
        value = changes[0].get("value", {})
        messages = value.get("messages", [])
        
        # Ignora eventos que não contêm mensagens (ex: status de entrega)
        if not messages: return 
        
        message = messages[0]
        phone = message.get("from")
        text_raw = message.get("text", {}).get("body", "")
        text_norm = normalizar_texto(text_raw)

        logger.info("Processando mensagem de %s: '%s'", phone, text_raw)

        # 2. Fluxo de Saudação
        if any(s in text_norm for s in ["ola", "oi", "bom dia", "boa tarde"]):
            logger.info("Saudação detectada, enviando menu.")
            # O send_themes_menu já é a função que busca e envia o menu
            if not await sender.send_themes_menu(phone):
                await sender.send_text(phone, "Menu indisponível no momento.")
            return

        # 3. Fluxo de Seleção de Tema
        if "energia" in text_norm and "mecanica" in text_norm:
            await sender.send_text(phone, "Carregando questão de Energia Mecânica...")
            # Aqui entrará a lógica de envio da questão
            return

        # 4. Fallback (Caso não entenda)
        await sender.send_text(phone, "Não entendi. Digite 'Ola' para ver o menu ou um tema de física.")
        
    except Exception as e:
        logger.error("Erro crítico no handler: %s", e)
