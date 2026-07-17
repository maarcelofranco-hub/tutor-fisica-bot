from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
import logging

from app.config import settings
from app.database import get_db
from app.models.schemas import IncomingMessage
from app.services.conversation import conversation_service
from app.services.question_provider import question_provider
from app.utils.phone import normalize_phone
# Importe a função que criamos para o Gemini decidir o tema
from app.services.llm import selecionar_tema_por_input 

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")

@router.post("/webhook")
async def receive_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception as e:
        return {"status": "error", "message": "Invalid JSON"}

    messages = _extract_messages(payload)
    
    for message in messages:
        try:
            # LÓGICA DE INTERCEPTAÇÃO DE TEMA
            estado_aluno = conversation_service.get_user_state(db, message.phone) 
            
            if estado_aluno == "WAITING_FOR_TOPIC":
                temas_disponiveis = question_provider.list_topics()
                tema_escolhido = selecionar_tema_por_input(message.text, temas_disponiveis)
                
                if tema_escolhido in temas_disponiveis:
                    await conversation_service.start_topic(db, message.phone, tema_escolhido)
                    continue 
                else:
                    await conversation_service.send_whatsapp_message(message.phone, tema_escolhido)
                    continue
            
            # Fluxo normal
            await conversation_service.handle_message(db, message)
        except Exception:
            logger.exception(f"Erro ao processar mensagem de {message.phone}")
            
    return {"status": "ok"}

def _extract_messages(payload: dict) -> list[IncomingMessage]:
    messages: list[IncomingMessage] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = {item.get("wa_id"): item.get("profile", {}).get("name") for item in value.get("contacts", [])}
            for item in value.get("messages", []):
                phone = normalize_phone(item.get("from", ""))
                if not phone: continue
                incoming = IncomingMessage(phone=phone, message_id=item.get("id", ""), contact_name=contacts.get(item.get("from")))
                message_type = item.get("type")
                if message_type == "text":
                    incoming.text = item.get("text", {}).get("body")
                elif message_type == "image":
                    incoming.text = item.get("image", {}).get("caption")
                messages.append(incoming)
    return messages
