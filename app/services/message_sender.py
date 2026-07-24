import logging
import time
import os
import re
import unicodedata
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
        Pré-carrega as imagens (questões) no cache.
        """
        from app.services.question_provider import question_provider
        logger.info("Iniciando processamento de cache (warmup) para questões...")
        
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

        logger.info("Processamento de cache de questões concluído!")

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

    async def send_resolution_image(self, phone: str, question_id: str, caption: str = "") -> None:
        """
        Busca a imagem da resolução correspondente à questão (mesmo número) no Drive.
        """
        start_time = time.time()
        logger.info("OUT [%s] resolution image para a questão: %s", phone, question_id)
        
        if not self.whatsapp.is_configured:
            return

        # Usamos o question_id + "_res" como chave de cache para a resolução
        res_cache_id = f"{question_id}_res"

        # 1. OLHA O CACHE PRIMEIRO (Performance)
        with next(get_db()) as db:
            cached = db.query(MediaCache).filter(MediaCache.drive_id == res_cache_id).first()
            if cached:
                logger.info("LOG TEMPO: Cache DB da Resolução consultado (%.2fs)", time.time() - start_time)
                await self.whatsapp.send_image_by_id(phone, cached.whatsapp_id, caption=caption)
                return

        # 2. INTELIGÊNCIA: ACHAR A RESOLUÇÃO CORRESPONDENTE NO DRIVE
        from app.services.question_provider import question_provider
        
        # Acessamos o _provider() direto para pular o filtro que esconde as resoluções
        provider = question_provider._provider()
        target_q = None
        target_topic = None
        
        # Descobrir o nome e o tópico da questão atual
        for topic in provider.list_topics():
            for q in provider.list_questions(topic):
                if q.id == question_id:
                    target_q = q
                    target_topic = topic
                    break
            if target_q:
                break
                
        if not target_q:
            logger.error("Erro: Questão original não encontrada no Drive.")
            return
            
        # Extrai o número do nome (Ex: "Questao1.jpg" -> "1")
        numbers = re.findall(r'\d+', target_q.name)
        if not numbers:
            logger.error(f"Erro: Não encontrei número no nome da questão {target_q.name}")
            return
        q_num = numbers[0]
        
        # Procura no mesmo tópico a resolução com o mesmo número
        resolucao_file = None
        for f in provider.list_questions(target_topic):
            name_norm = ''.join(c for c in unicodedata.normalize('NFD', f.name) if unicodedata.category(c) != 'Mn').lower()
            # Busca por "resoluca" ou "reoluca" (caso haja erro de digitação) + o número da questão
            if ("resoluca" in name_norm or "reoluca" in name_norm) and q_num in name_norm:
                resolucao_file = f
                break
                
        if not resolucao_file:
            logger.error(f"Erro: Imagem de resolução não encontrada para a questão {target_q.name}")
            return
            
        # Baixa a imagem da resolução oficial do Drive/Pasta
        res_bytes, res_mime_type = provider.get_question_image(resolucao_file.id)

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
