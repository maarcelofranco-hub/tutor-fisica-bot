import io
import logging
from PIL import Image
from app.services.gemini import GeminiService

logger = logging.getLogger(__name__)

class OCRService:
    def __init__(self, gemini_service: GeminiService) -> None:
        self.gemini = gemini_service

    async def process_answer(self, message, question_id: str) -> str:
        """
        Lê a resposta do aluno e corrige. A resolução em LaTeX já foi
        criada pela rotina de sincronização de 6 em 6 horas!
        """
        student_text = message.text or ""
        
        # Faz o OCR se o aluno mandou foto
        if hasattr(message, 'image_bytes') and message.image_bytes:
            try:
                extracted = await self.extract_text(message.image_bytes)
                student_text = f"{student_text}\n{extracted}".strip()
            except Exception as e:
                logger.error(f"Erro ao extrair texto da imagem do aluno: {e}")

        if not student_text:
            student_text = "O aluno enviou uma imagem, mas não consegui ler o texto."

        # Corrije a questão instantaneamente
        return await self.gemini.correct_answer(student_text, question_id)

    async def extract_text(self, image_bytes: bytes, mime_type: str = "image/png") -> str:
        prepared = self._prepare_image(image_bytes)
        return await self.gemini.extract_text_from_image(prepared, mime_type)

    def _prepare_image(self, image_bytes: bytes) -> bytes:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=90)
        return output.getvalue()
