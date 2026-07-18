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
        Orquestra todo o processo de análise quando o aluno envia uma resposta.
        É aqui que garantimos que a resolução em LaTeX seja gerada!
        """
        # ========================================================
        # 1. O GATILHO DE ALTA PERFORMANCE
        # ========================================================
        # Antes de analisar o aluno, mandamos o Gemini verificar se a imagem 
        # da resolução já existe. Se não existir, ele cria e salva no /tmp/ agora!
        try:
            await self.gemini.get_or_create_resolution_image(question_id)
        except Exception as e:
            logger.error(f"Aviso: Falha ao pré-gerar imagem de resolução: {e}")

        # ========================================================
        # 2. LÊ A RESPOSTA DO ALUNO
        # ========================================================
        student_text = message.text or ""
        
        # Verifica se a mensagem veio com imagem para fazer o OCR
        # (Ajuste 'image_bytes' para o nome correto que você usa no seu IncomingMessage)
        if hasattr(message, 'image_bytes') and message.image_bytes:
            try:
                extracted = await self.extract_text(message.image_bytes)
                student_text = f"{student_text}\n{extracted}".strip()
            except Exception as e:
                logger.error(f"Erro ao extrair texto da imagem do aluno: {e}")

        # Fallback de segurança caso o OCR falhe ou venha vazio
        if not student_text:
            student_text = "O aluno enviou uma imagem, mas não consegui ler o texto perfeitamente."

        # ========================================================
        # 3. CORRIGE A QUESTÃO
        # ========================================================
        feedback = await self.gemini.correct_answer(student_text, question_id)
        
        return feedback

    async def extract_text(self, image_bytes: bytes, mime_type: str = "image/png") -> str:
        prepared = self._prepare_image(image_bytes)
        return await self.gemini.extract_text_from_image(prepared, mime_type)

    def _prepare_image(self, image_bytes: bytes) -> bytes:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=90)
        return output.getvalue()
