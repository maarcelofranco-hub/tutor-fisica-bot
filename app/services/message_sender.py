import logging
import time
from app.config import settings
from app.services.outbox import outbox
from app.services.whatsapp import WhatsAppService
from app.database import get_db, MediaCache

logger = logging.getLogger(__name__)

class MessageSender:
    def __init__(self) -> None:
        self.whatsapp = WhatsAppService()

    async def send_text(self, phone: str, text: str) -> None:
        outbox.add_text(phone, text)
        logger.info("OUT [%s] text: %s", phone, text[:160])
        if self.whatsapp.is_configured:
            await self.whatsapp.send_text(phone, text)

    # --- NOVO MÉTODO PARA A RESOLUÇÃO DE ELITE ---
    async def send_image(self, phone: str, image_path: str, caption: str = "") -> None:
        """
        Envia uma imagem gerada localmente (resolução de elite) para o WhatsApp.
        """
        if not self.whatsapp.is_configured:
            return

        with open(image_path, "rb") as f:
            image_bytes = f.read()
        
        # Usa o método de upload que você já tem no seu WhatsAppService
        media_id = await self.whatsapp._upload_media(image_bytes, "image/png")
        await self.whatsapp.send_image_by_id(phone, media_id, caption=caption)
        
        logger.info(f"Resolução enviada para {phone}: {image_path}")

    async def send_question_image(
        self,
        phone: str,
        caption: str,
        image_bytes: bytes = None,
        mime_type: str = None,
        image_url: str | None = None,
        question_id: str = None
    ) -> None:
        start_time = time.time()
        outbox.add_image(phone, caption, caption=caption)
        logger.info("OUT [%s] image: %s", phone, caption)
        
        if not self.whatsapp.is_configured:
            return

        # 1. OLHA O CACHE PRIMEIRO
        if question_id:
            with next(get_db()) as db:
                cached = db.query(MediaCache).filter(MediaCache.drive_id == question_id).first()
                if cached:
                    logger.info("LOG TEMPO: Cache DB consultado (%.2fs)", time.time() - start_time)
                    await self.whatsapp.send_image_by_id(phone, cached.whatsapp_id, caption=caption)
                    return

        # 2. SE NÃO TEM CACHE, BAIXA DO DRIVE
        if not image_bytes and question_id:
            from app.services.question_provider import question_provider
            image_bytes, mime_type = question_provider.get_question_image(question_id)

        if not image_bytes:
            logger.error("Erro: Nenhuma imagem fornecida para envio.")
            return

        # 3. FAZ O UPLOAD E ENVIA
        media_id = await self.whatsapp._upload_media(image_bytes, mime_type)
        await self.whatsapp.send_image_by_id(phone, media_id, caption=caption)
        
        # 4. SALVA NO CACHE
        if question_id:
            with next(get_db()) as db:
                new_cache = MediaCache(drive_id=question_id, whatsapp_id=media_id)
                db.add(new_cache)
                db.commit()

    async def send_document(
        self, phone: str, file_bytes: bytes, mime_type: str, filename: str, caption: str | None = None,
    ) -> None:
        outbox.add_text(phone, f"[documento] {filename}")
        if self.whatsapp.is_configured:
            await self.whatsapp.send_document_bytes(phone, file_bytes, mime_type, filename, caption=caption)
