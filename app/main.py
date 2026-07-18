import asyncio
import http
import httpx
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.api.test import router as test_router
from app.api.webhook import router as webhook_router
from app.database import init_db
from app.logging_config import setup_logging
from app.config import settings
from app.services.message_sender import MessageSender

# Importamos o question_provider para rodar a varredura e o Gemini!
from app.services.question_provider import question_provider 

logger = logging.getLogger(__name__)

# Tarefa de ping para evitar suspensão por inatividade
async def keep_alive():
    async with httpx.AsyncClient() as client:
        while True:
            try:
                # Faz um ping na rota /health para manter o serviço ativo
                await client.get("https://tutor-fisica-bot.onrender.com/health")
                print("Ping de manutenção realizado com sucesso!")
            except Exception as e:
                print(f"Erro no ping: {e}")
            await asyncio.sleep(600)  # Intervalo de 10 minutos

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
    # Inicia a tarefa de ping em segundo plano
    ping_task = asyncio.create_task(keep_alive())
    
    setup_logging()
    init_db()
    
    # Inicia o agendador de cache
    scheduler = AsyncIOScheduler()
    
    # =========================================================
    # 🎯 ALTERADO PARA 20 MINUTOS AQUI!
    # =========================================================
    scheduler.add_job(run_warmup_job, 'interval', minutes=20)
    scheduler.add_job(run_warmup_job, 'date')  # Roda uma vez no boot
    scheduler.start()
    
    yield
    
    scheduler.shutdown()
    ping_task.cancel()

app = FastAPI(lifespan=lifespan)

app.include_router(test_router)
app.include_router(webhook_router)
