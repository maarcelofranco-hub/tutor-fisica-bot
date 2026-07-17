import logging
import time
from fastapi import APIRouter, Request, BackgroundTasks
from app.services.message_sender import MessageSender
from app.api.handler import handle_message

router = APIRouter()
logger = logging.getLogger(__name__)

async def process_message(data: dict):
    """
    Função processada em segundo plano para não travar a resposta do Webhook.
    Isso é crucial para evitar o timeout e a latência de 8 segundos.
    """
    try:
        sender = MessageSender()
        await handle_message(data, sender)
    except Exception as e:
        logger.error("Erro no processamento da mensagem: %s", e)

@router.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    start_time = time.time()
    data = await request.json()
    
    # Validação rápida de payload do WhatsApp
    if not data.get("entry"):
        return {"status": "ok"}

    # Dispara o processamento em BACKGROUND e retorna imediatamente 200 OK
    background_tasks.add_task(process_message, data)
    
    process_time = time.time() - start_time
    logger.info("Webhook recebido e disparado em segundo plano (Tempo: %.4fs)", process_time)
    
    return {"status": "accepted"}
