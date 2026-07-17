import asyncio
import httpx
import sys
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.api.test import router as test_router
from app.api.webhook import router as webhook_router
from app.database import init_db
from app.logging_config import setup_logging
from app.config import settings

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

@asynccontextmanager
async def lifespan(_: FastAPI):
    # Inicia a tarefa de ping em segundo plano
    ping_task = asyncio.create_task(keep_alive())
    
    setup_logging()
    init_db()
    
    if settings.drive_sync_on_startup:
        import subprocess
        from pathlib import Path

        logger = logging.getLogger(__name__)
        script = Path(__file__).resolve().parents[1] / "scripts" / "sync_drive_gdown.py"
        if script.exists():
            logger.info("Syncing Google Drive folder on startup...")
            subprocess.run([sys.executable, str(script)], check=False)
    
    yield
    
    # Cancela a tarefa ao encerrar o servidor
    ping_task.cancel()

app = FastAPI(
    title="WhatsApp Physics Tutor",
    description="Backend MVP para ensino de Fisica via WhatsApp + Gemini",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(webhook_router)
app.include_router(test_router)

@app.get("/health")
def health_check():
    from app.services.question_provider import question_provider

    topics = question_provider.list_topics()
    themes_menu = question_provider.get_themes_menu_file()
    return {
        "status": "ok",
        "question_source": question_provider.mode,
        "topics": topics,
        "themes_menu": themes_menu.name if themes_menu else None,
        "drive_configured": question_provider.drive.is_configured,
    }
