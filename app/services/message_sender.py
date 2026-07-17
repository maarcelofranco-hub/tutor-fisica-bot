import logging
from app.config import settings
from app.services.outbox import outbox
from app.services.whatsapp import WhatsAppService

logger = logging.getLogger(__name__)

class MessageSender:
    # Cache em memória para IDs do WhatsApp
    _media_cache: dict[str, str] = {}

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
        question_id: str = None
    ) -> None:
        outbox.add_image(phone, caption, caption=caption)
        logger.info("OUT [%s] image: %s", phone, caption)
        
        if not self.whatsapp.is_configured:
            return

        # 1. TENTA USAR O CACHE
        if question_id and question_id in self._media_cache:
            logger.info("Usando CACHE de media_id para a questão %s", question_id)
            await self.whatsapp.send_image_by_id(phone, self._media_cache[question_id], caption=caption)
            return

        # 2. SE NÃO TEM CACHE, FAZ O UPLOAD E GUARDA
        logger.info("Realizando UPLOAD da imagem para o WhatsApp...")
        media_id = await self.whatsapp._upload_media(image_bytes, mime_type)
        
        # Envia usando o ID que acabou de receber
        await self.whatsapp.send_image_by_id(phone, media_id, caption=caption)
        
        # 3. SALVA NO CACHE
        if question_id:
            self._media_cache[question_id] = media_id
            logger.info("Media ID %s salvo no cache para a questão %s", media_id, question_id)

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
        instruction = "Escolha um tema no PDF abaixo. Resolva a questão e me envie sua resposta para correção!"
        
        if mime_type == "application/pdf" or menu_file.name.lower().endswith(".pdf"):
            await self.send_text(phone, instruction)
            await self.send_document(phone, file_bytes, "application/pdf", menu_file.name)
            return True
            
        if mime_type.startswith("image/"):
            await self.send_question_image(
                phone=phone,
                image_bytes=file_bytes,
                mime_type=mime_type,
                caption=instruction,
                question_id=menu_file.id
            )
            return True
        return False
