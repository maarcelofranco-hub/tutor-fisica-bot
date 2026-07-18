import logging
import time
import os
from app.config import settings
from app.services.outbox import outbox
from app.services.whatsapp import WhatsAppService
from app.database import get_db, MediaCache

logger = logging.getLogger(__name__)

class MessageSender:
    def __init__(self) -> None:
        self.whatsapp = WhatsAppService()

    async def warm_up_cache_on_whatsapp(self) -> None:
        """
        Pré-carrega as imagens (questões e resoluções) no cache.
        """
        from app.services.question_provider import question_provider
        logger.info("Iniciando processamento de cache (warmup) para questões e resoluções...")
        
        for topic in question_provider.list_topics():
            for question in question_provider.list_questions(topic):
                # ==========================================
                # 1. CACHE DA IMAGEM DA QUESTÃO
                # ==========================================
                image_bytes, mime_type = question_provider.get_question_image(question.id)
                
                if image_bytes:
                    with next(get_db()) as db:
                        if not db.query(MediaCache).filter(MediaCache.drive_id == question.id).first():
                            media_id = await self.whatsapp._upload_media(image_bytes, mime_type)
                            new_cache = MediaCache(drive_id=question.id, whatsapp_id=media_id)
                            db.add(new_cache)
                            db.commit()
                            logger.info(f"Cache populado para a questão: {question.id}")

                # ==========================================
                # 2. CACHE DA IMAGEM DA RESOLUÇÃO (NOVO)
                # ==========================================
                # Como o seu resolution_generator salva a imagem no disco, 
                # vamos ler o ficheiro diretamente.
                # IMPORTANTE: Ajuste este caminho ('resolucoes') para a pasta correta onde as imagens são salvas!
                res_path = f"resolucoes/{question.id}.png" 
                
                if os.path.exists(res_path):
                    with open(res_path, "rb") as f:
                        res_bytes = f.read()
                    res_mime_type = "image/png"
                    
                    res_cache_id = f"{question.id}_res"
                    with next(get_db()) as db:
                        if not db.query(MediaCache).filter(MediaCache.drive_id == res_cache_id).first():
                            res_media_id = await self.whatsapp._upload_media(res_bytes, res_mime_type)
                            new_res_cache = MediaCache(drive_id=res_cache_id, whatsapp_id=res_media_id)
                            db.add(new_res_cache)
                            db.commit()
                            logger.info(f"Cache populado para a resolução: {question.id}")
                else:
                    logger.warning(f"Imagem de resolução não encontrada no disco para warmup: {res_path}")
        
        logger.info("Processamento de cache concluído com sucesso!")

    async def send_text(self, phone: str, text: str) -> None:
        outbox.add_text(phone, text)
        logger.info("OUT [%s] text: %s", phone, text[:160])
        if self.whatsapp.is_configured:
            await self.whatsapp.send_text(phone, text)

    async def send_image(self, phone: str, image_path: str, caption: str = "") -> None:
        if not self.whatsapp.is_configured:
            return

        with open(image_path, "rb") as f:
            image_bytes = f.read()
        
        media_id = await self.whatsapp._upload_media(image_bytes, "image/png")
        await self.whatsapp.send_image_by_id(phone, media_id, caption=caption)
        
        logger.info(f"Imagem local enviada para {phone}: {image_path}")

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
        logger.info("OUT [%s] question image: %s", phone, caption)
        
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

    async def send_resolution_image(self, phone: str, question_id: str, caption: str = "Aqui está a resolução passo a passo:") -> None:
        """
        NOVO MÉTODO: Busca a imagem da resolução no cache ou faz o upload se não existir, e envia.
        """
        start_time = time.time()
        logger.info("OUT [%s] resolution image para a questão: %s", phone, question_id)
        
        if not self.whatsapp.is_configured:
            return

        res_cache_id = f"{question_id}_res"

        # 1. OLHA O CACHE PRIMEIRO (Performance)
        with next(get_db()) as db:
            cached = db.query(MediaCache).filter(MediaCache.drive_id == res_cache_id).first()
            if cached:
                logger.info("LOG TEMPO: Cache DB da Resolução consultado (%.2fs)", time.time() - start_time)
                await self.whatsapp.send_image_by_id(phone, cached.whatsapp_id, caption=caption)
                return

        # 2. SE NÃO TEM CACHE, TENTA LER DO DISCO NA HORA
        res_path = f"resolucoes/{question_id}.png"
        if not os.path.exists(res_path):
            logger.error(f"Erro: Nenhuma imagem de resolução encontrada em {res_path}.")
            return
            
        with open(res_path, "rb") as f:
            res_bytes = f.read()
        res_mime_type = "image/png"

        # 3. FAZ O UPLOAD E ENVIA
        media_id = await self.whatsapp._upload_media(res_bytes, res_mime_type)
        await self.whatsapp.send_image_by_id(phone, media_id, caption=caption)
        
        # 4. SALVA NO CACHE PARA A PRÓXIMA
        with next(get_db()) as db:
            new_cache = MediaCache(drive_id=res_cache_id, whatsapp_id=media_id)
            db.add(new_cache)
            db.commit()

    async def send_document(
        self, phone: str, file_bytes: bytes, mime_type: str, filename: str, caption: str | None = None,
    ) -> None:
        outbox.add_text(phone, f"[documento] {filename}")
        if self.whatsapp.is_configured:
            await self.whatsapp.send_document_bytes(phone, file_bytes, mime_type, filename, caption=caption)
