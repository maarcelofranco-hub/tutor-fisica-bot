# app/api/handler.py
import logging

logger = logging.getLogger(__name__)

async def handle_message(data: dict, sender):
    logger.info("Mensagem recebida para processamento: %s", data)
    # Aqui ficará a lógica de tratamento das mensagens
    pass
