import logging

from app.config import settings
from app.services.outbox import outbox
from app.services.whatsapp import WhatsAppService

logger = logging.getLogger(__name__)


class MessageSender:
    def __init__(self) -> None:
        self.whatsapp = WhatsAppService()

    async def send_text(self, phone: str, text: str) -> None:
        outbox.add_text(phone, text)
        logger.info("OUT [%s] text: %s", phone, text[:160])
        if self.whatsapp.is_configured:
            await self.whatsapp.send_text(phone, text)

    async def send_question_image(
        self,
        phone: str,
        image_bytes: bytes,
        mime_type: str,
        caption: str,
        image_url: str | None = None,
    ) -> None:
        outbox.add_image(phone, caption, caption=caption)
        logger.info("OUT [%s] image: %s", phone, caption)
        if not self.whatsapp.is_configured:
            return
        await self.whatsapp.send_image_bytes(phone, image_bytes, mime_type, caption=caption)

    async def send_document(
        self,
        phone: str,
        file_bytes: bytes,
        mime_type: str,
        filename: str,
        caption: str | None = None,
    ) -> None:
        outbox.add_text(phone, f"[documento] {filename}")
        logger.info("OUT [%s] document: %s", phone, filename)
        if self.whatsapp.is_configured:
            await self.whatsapp.send_document_bytes(phone, file_bytes, mime_type, filename, caption=caption)

    async def send_themes_menu(self, phone: str) -> bool:
        from app.services.question_provider import question_provider

        menu_file = question_provider.get_themes_menu_file()
        if not menu_file:
            return False
        file_bytes, mime_type = question_provider.download_file(menu_file.id)
        if mime_type == "application/pdf" or menu_file.name.lower().endswith(".pdf"):
            await self.send_document(phone, file_bytes, "application/pdf", menu_file.name)
            return True
        if mime_type.startswith("image/"):
            await self.send_question_image(
                phone=phone,
                image_bytes=file_bytes,
                mime_type=mime_type,
                caption="Opcoes de temas",
            )
            return True
        return False

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        return await self.whatsapp.download_media(media_id)
