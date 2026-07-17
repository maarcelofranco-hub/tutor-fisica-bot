import json
import logging
import re
from google import genai
from app.config import settings
from app.models.schemas import CorrectionResult

logger = logging.getLogger(__name__)

class GeminiService:
    def __init__(self) -> None:
        self.enabled = bool(settings.gemini_api_key)
        self.model_name = settings.gemini_model

    def _get_client(self):
        return genai.Client(api_key=settings.gemini_api_key)

    async def extract_text_from_image(self, image_bytes: bytes, mime_type: str) -> str:
        if not self.enabled:
            return "[modo teste] resposta extraida da imagem"
        
        client = self._get_client()
        prompt = "Extraia somente o conteudo escrito pelo aluno nesta imagem de resposta. Retorne apenas o texto encontrado."
        
        response = client.models.generate_content(
            model=self.model_name,
            contents=[
                prompt,
                {"inline_data": {"data": image_bytes, "mime_type": mime_type}}
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
            return CorrectionResult(is_correct=True, feedback="[Modo teste] Resposta recebida.", explanation=None)

        client = self._get_client()
        prompt = self._build_prompt(student_answer, answer_key)
        
        contents = [prompt]
        
        if question_image_bytes:
            contents.append({
                "inline_data": {
                    "data": question_image_bytes,
                    "mime_type": question_mime_type
                }
            })

        # Aumento do max_output_tokens para 500 para evitar cortes no JSON
        response = client.models.generate_content(
            model=self.model_name, 
            contents=contents,
            config={"max_output_tokens": 500, "temperature": 0.1}
        )
        return self._parse_response(response.text or "", student_answer)

    def _build_prompt(self, student_answer: str, answer_key: str | None) -> str:
        return f"""
        Você é um assistente de física que foca apenas na resolução matemática.
        Avalie a resposta do aluno: '{student_answer}'. Esperado: '{answer_key}'.
        
        Se a resposta estiver incorreta, forneça a resolução seguindo ESTRITAMENTE este formato minimalista:
        
        *DADOS*
        (Liste apenas variáveis: valores)
        
        *RESOLUÇÃO*
        (Apenas passos matemáticos, um por linha. Ex:
        4 / 3.6 = 1.11
        1.8 = 5 * t²
        t = 0.6)
        
        *RESPOSTA*
        (Valor final com unidade)
        
        Retorne em JSON com as chaves: 
        - 'is_correct' (boolean)
        - 'feedback' (curtíssimo)
        - 'explanation' (o texto acima, formatado)
        """

    def _parse_response(self, response_text: str, original_answer: str) -> CorrectionResult:
        try:
            # Remove blocos de markdown
            clean_text = re.sub(r'^```json\s*|\s*
