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

        # 1. OLHA O CACHE PRIMEIRO (Fração de segundo)
        if question_id:
            with next(get_db()) as db:
                cached = db.query(MediaCache).filter(MediaCache.drive_id == question_id).first()
                if cached:
                    logger.info("LOG TEMPO: Cache DB consultado (%.2fs)", time.time() - start_time)
                    await self.whatsapp.send_image_by_id(phone, cached.whatsapp_id, caption=caption)
                    logger.info("LOG TEMPO: Envio via API concluído (%.2fs totais)", time.time() - start_time)
                    return

        # 2. SE NÃO TEM CACHE, AÍ SIM ELE BAIXA DO DRIVE (Leva os ~3 segundos)
        if not image_bytes and question_id:
            logger.info("Imagem não estava no cache. Baixando do Drive...")
            from app.services.question_provider import question_provider
            image_bytes, mime_type = question_provider.get_question_image(question_id)

        if not image_bytes:
            logger.error("Erro: Nenhuma imagem fornecida para envio.")
            return

        # 3. FAZ O UPLOAD E ENVIA (Leva os ~4 segundos adicionais)
        logger.info("Realizando UPLOAD da imagem para o WhatsApp...")
        media_id = await self.whatsapp._upload_media(image_bytes, mime_type)
        await self.whatsapp.send_image_by_id(phone, media_id, caption=caption)
        
        # 4. SALVA NO CACHE PARA A PRÓXIMA VEZ SER INSTANTÂNEO
        if question_id:
            with next(get_db()) as db:
                new_cache = MediaCache(drive_id=question_id, whatsapp_id=media_id)
                db.add(new_cache)
                db.commit()
                logger.info("Media ID salvo no DB para %s", question_id)

    async def warm_up_cache_on_whatsapp(self):
        from app.services.question_provider import question_provider
        
        logger.info("Iniciando pré-upload...")
        topics = question_provider.list_topics()
        for topic in topics:
            questions = question_provider.list_questions(topic)
            for q in questions:
                with next(get_db()) as db:
                    if db.query(MediaCache).filter(MediaCache.drive_id == q.id).first():
                        continue
                
                img_bytes, mime = question_provider.get_question_image(q.id)
                media_id = await self.whatsapp._upload_media(img_bytes, mime)
                
                with next(get_db()) as db:
                    db.add(MediaCache(drive_id=q.id, whatsapp_id=media_id))
                    db.commit()
        logger.info("Pré-upload concluído!")

    async def send_document(
        self, phone: str, file_bytes: bytes, mime_type: str, filename: str, caption: str | None = None,
    ) -> None:
        outbox.add_text(phone, f"[documento] {filename}")
        if self.whatsapp.is_configured:
            await self.whatsapp.send_document_bytes(phone, file_bytes, mime_type, filename, caption=caption)

    async def send_themes_menu(self, phone: str) -> bool:
        start_menu_time = time.time()
        from app.services.question_provider import question_provider
        
        menu_file = question_provider.get_themes_menu_file()
        if not menu_file: 
            return False
        
        logger.info("LOG TEMPO: Iniciando download do arquivo do menu do Drive...")
        file_bytes, mime_type = question_provider.download_file(menu_file.id)
        instruction = "Escolha um tema. Resolva e me envie sua resposta!"
        
        if mime_type.startswith("image/"):
            await self.send_question_image(
                phone, 
                caption=instruction, 
                image_bytes=file_bytes, 
                mime_type=mime_type, 
                question_id=menu_file.id
            )
            return True
            
        return False
