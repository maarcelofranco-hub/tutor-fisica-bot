import logging
from app.services.message_sender import MessageSender
import unicodedata

logger = logging.getLogger(__name__)

def normalizar_texto(texto: str) -> str:
    """Remove acentos e converte para minúsculas para facilitar a comparação."""
    texto = texto.lower()
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

async def handle_message(data: dict, sender: MessageSender):
    try:
        # Extração segura dos dados
        entry = data.get("entry", [])[0]
        change = entry.get("changes", [])[0]
        value = change.get("value", {})
        message = value.get("messages", [])[0]
        
        phone = message.get("from")
        text_raw = message.get("text", {}).get("body", "")
        text_norm = normalizar_texto(text_raw)

        logger.info("Processando mensagem de %s: '%s'", phone, text_raw)

        # 1. Fluxo de Saudação
        if any(saudacao in text_norm for saudacao in ["ola", "oi", "bom dia", "boa tarde"]):
            logger.info("Saudação detectada, enviando menu.")
            if not await sender.send_themes_menu(phone):
                await sender.send_text(phone, "Menu indisponível.")
            return

        # 2. Fluxo de Temas (Exemplo: Energia Mecânica)
        if "energia" in text_norm and "mecanica" in text_norm:
            await sender.send_text(phone, "Carregando questão de Energia Mecânica...")
            # Aqui você chamaria sua função para enviar a questão específica
            return

        # 3. Fallback (Caso não entenda)
        await sender.send_text(phone, "Não entendi. Digite 'Ola' para ver o menu ou um tema de física.")
        
    except Exception as e:
        logger.error("Erro crítico no handler: %s", e)
