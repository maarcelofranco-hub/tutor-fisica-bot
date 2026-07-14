from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Contact, StudentProgress, StudentSession, get_db
from app.models.schemas import IncomingMessage
from app.services.conversation import conversation_service
from app.utils.phone import normalize_phone

router = APIRouter()


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
    import logging

    logger = logging.getLogger(__name__)
    payload = await request.json()
    messages = _extract_messages(payload)
    statuses = _extract_statuses(payload)
    if messages:
        logger.info(
            "Webhook received %s message(s): %s",
            len(messages),
            [(m.phone, (m.text or "")[:80], m.media_id) for m in messages],
        )
    elif statuses:
        logger.debug("Webhook status-only payload (%s statuses)", len(statuses))
    for status in statuses:
        if status.get("status") == "failed":
            logger.error(
                "WhatsApp delivery FAILED id=%s recipient=%s errors=%s",
                status.get("id"),
                status.get("recipient_id"),
                status.get("errors"),
            )
        else:
            logger.info(
                "WhatsApp status=%s id=%s recipient=%s",
                status.get("status"),
                status.get("id"),
                status.get("recipient_id"),
            )
    for message in _extract_messages(payload):
        try:
            await conversation_service.handle_message(db, message)
        except Exception:
            logger.exception("Failed to handle WhatsApp message from %s", message.phone)
    return {"status": "ok"}


def _extract_statuses(payload: dict) -> list[dict]:
    statuses: list[dict] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for item in change.get("value", {}).get("statuses", []):
                statuses.append(item)
    return statuses


def _extract_messages(payload: dict) -> list[IncomingMessage]:
    messages: list[IncomingMessage] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = {
                item.get("wa_id"): item.get("profile", {}).get("name")
                for item in value.get("contacts", [])
            }
            for item in value.get("messages", []):
                phone = normalize_phone(item.get("from", ""))
                if not phone:
                    continue

                incoming = IncomingMessage(
                    phone=phone,
                    message_id=item.get("id", ""),
                    contact_name=contacts.get(item.get("from")),
                )

                message_type = item.get("type")
                if message_type == "text":
                    incoming.text = item.get("text", {}).get("body")
                elif message_type == "image":
                    image = item.get("image", {})
                    incoming.media_id = image.get("id")
                    incoming.media_mime_type = image.get("mime_type")
                    incoming.text = image.get("caption")

                messages.append(incoming)
    return messages
