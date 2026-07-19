import logging
import time
from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import PlainTextResponse
from app.services.message_sender import MessageSender
from app.api.handler import handle_message

router = APIRouter()
logger = logging.getLogger(__name__)

# --- ROTA DE VERIFICAÇÃO (Necessária para o painel da Meta) ---
@router.get("/webhook")
async def verify(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == "physics-mvp-verify-2026-himari":
        return PlainTextResponse(challenge)
    return PlainTextResponse("Token inválido", status_code=403)

# --- ROTA DE MENSAGENS (O que você já tinha, está ótimo!) ---
async def process_message(data: dict):
    try:
        sender = MessageSender()
        await handle_message(data, sender)
    except Exception as e:
        logger.error("Erro no processamento da mensagem: %s", e)

@router.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    start_time = time.time()
    data = await request.json()
    
    if not data.get("entry"):
        return {"status": "ok"}

    background_tasks.add_task(process_message, data)
    
    process_time = time.time() - start_time
    logger.info("Webhook recebido e disparado em segundo plano (Tempo: %.4fs)", process_time)
    
    return {"status": "accepted"}
