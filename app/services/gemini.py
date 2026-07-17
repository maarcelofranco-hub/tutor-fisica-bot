import json
import logging
import re
from google import genai
from google.genai import types

from app.config import settings
from app.models.schemas import CorrectionResult

logger = logging.getLogger(__name__)

class GeminiService:
    def __init__(self) -> None:
        self.enabled = bool(settings.gemini_api_key)
        if self.enabled:
            # Inicialização com o novo cliente
            self.client = genai.Client(api_key=settings.gemini_api_key)
            self.model_name = settings.gemini_model
        else:
            self.client = None
            logger.warning("GEMINI_API_KEY not set. Using mock correction mode.")

    async def extract_text_from_image(self, image_bytes: bytes, mime_type: str) -> str:
        if not self.enabled:
            return "[modo teste] resposta extraida da imagem"
        
        prompt = (
            "Extraia somente o conteudo escrito pelo aluno nesta imagem de resposta. "
            "Retorne apenas o texto encontrado."
        )
        
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=[
                prompt,
                types.Part.from_data(data=image_bytes, mime_type=mime_type)
            ]
        )
        return (response.text or "").strip()

    async def correct_answer(
        self,
        question_image_bytes: bytes | None,
        question_mime_type: str,
        student_answer: str,
        answer_key: str | None = None,
    ) -> CorrectionResult:
        if not self.enabled:
            return CorrectionResult(
                is_correct=True,
                feedback="[Modo teste] Resposta recebida.",
                explanation=None,
            )

        prompt = self._build_prompt(student_answer, answer_key)
        parts = [prompt]
        if question_image_bytes:
            parts.append(types.Part.from_data(data=question_image_bytes, mime_type=question_mime_type))

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=parts
        )
        return self._parse_response(response.text or "", student_answer)

    def _build_prompt(self, student_answer: str, answer_key: str | None) -> str:
        prompt = f"O aluno respondeu: '{student_answer}'. "
        if answer_key:
            prompt += f"A resposta correta esperada é: '{answer_key}'. "
        prompt += (
            "Avalie se a resposta do aluno está correta. "
            "Retorne a resposta no formato JSON estrito com as chaves: "
            "'is_correct' (boolean), 'feedback' (string) e 'explanation' (string)."
        )
        return prompt

    def _parse_response(self, response_text: str, original_answer: str) -> CorrectionResult:
        try:
            # Remove marcações de markdown caso o Gemini retorne
            clean_text = re.sub(r'^```json\s*|\s*```$', '', response_text.strip(), flags=re.MULTILINE)
            data = json.loads(clean_text)
            return CorrectionResult(
                is_correct=data.get("is_correct", False),
                feedback=data.get("feedback", "Sem feedback"),
                explanation=data.get("explanation")
            )
        except Exception as e:
            logger.error(f"Erro ao processar resposta do Gemini: {e}")
            return CorrectionResult(
                is_correct=False,
                feedback="Erro ao processar correção.",
                explanation=f"O modelo retornou: {response_text}"
            )
