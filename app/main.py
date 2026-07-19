import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.api.test import router as test_router
from app.api.webhook import router as webhook_router
from app.database import init_db
from app.logging_config import setup_logging
from app.services.message_sender import MessageSender
from app.services.question_provider import question_provider 

logger = logging.getLogger(__name__)

async def run_warmup_job():
    logger.info("Executando varredura no Drive e tarefa de pre-upload (20 min)...")
    try:
        # 1. Puxa do Drive e aciona o Gemini para gerar as resoluções em LaTeX
        await question_provider.refresh()
        
        # 2. Sobe as imagens (questões + resoluções) para o WhatsApp e salva no SQL
        sender = MessageSender()
        await sender.warm_up_cache_on_whatsapp()
        
    except Exception as e:
        logger.error(f"Erro na varredura/warmup automático: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_db()
    
    # Inicia o agendador de cache
    scheduler = AsyncIOScheduler()
    
    # Executa a cada 20 minutos
    scheduler.add_job(run_warmup_job, 'interval', minutes=20)
    scheduler.add_job(run_warmup_job, 'date')  # Roda uma vez no boot
    scheduler.start()
    
    yield
    
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)

app.include_router(test_router)
app.include_router(webhook_router)
