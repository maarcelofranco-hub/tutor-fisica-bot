import json
import logging
import re
from google import genai
from app.config import settings
from app.models.schemas import CorrectionResult
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

class GeminiService:
    def __init__(self) -> None:
        self.enabled = bool(settings.gemini_api_key)
        self.model_name = settings.gemini_model

    def _get_client(self):
        return genai.Client(api_key=settings.gemini_api_key)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def correct_answer(
        self,
        question_image_bytes: bytes | None,
        question_mime_type: str,
        student_answer: str,
        answer_key: str | None = None,
    ) -> CorrectionResult:
        if not self.enabled:
            return CorrectionResult(is_correct=True, feedback="[Modo teste]", explanation=None)

        client = self._get_client()
        prompt = self._build_prompt(student_answer, answer_key)
        
        contents = [prompt]
        if question_image_bytes:
            contents.append({
                "inline_data": {"data": question_image_bytes, "mime_type": question_mime_type}
            })

        response = client.models.generate_content(
            model=self.model_name, 
            contents=contents,
            config={"temperature": 0.1}
        )
        return self._parse_response(response.text or "", student_answer)

    def _build_prompt(self, student_answer: str, answer_key: str | None) -> str:
        return f"""
        Você é um professor de física renomado. Avalie: '{student_answer}'. Gabarito: '{answer_key}'.
        
        Se a resposta estiver incorreta, forneça a resolução seguindo estas regras estritas:
        
        1. FORMATAÇÃO: Use um ponto final antes de títulos (ex: .Equacionamento). Pule UMA LINHA entre cada linha de cálculo para manter a organização.
        
        2. ESTILO "LIVRO DIDÁTICO":
           - NÃO explique cada passo algébrico (evite frases como "multiplicamos por", "cancelamos").
           - Apenas apresente as equações organizadas verticalmente.
           - Use apenas números na substituição.
           
        3. NOTAÇÃO:
           - Use "√" para raiz e "²" para potência.
           - NÃO use 'sqrt' ou '^2'.
           
        4. EXEMPLO DE SAÍDA (Siga este formato):
           .Equacionamento
           g * h = 0.5 * v²
           
           .Substituição
           10 * 2.45 = 0.5 * v²
           24.5 = 0.5 * v²
           v² = 49
           v = √49
           v = 7 m/s
        
        Retorne APENAS um objeto JSON com as chaves: "is_correct" (boolean), "feedback" (string curta), "explanation" (resolução formatada).
        """

    def _parse_response(self, response_text: str, original_answer: str) -> CorrectionResult:
        try:
            # Re.DOTALL permite que o JSON contenha quebras de linha (\n) sem quebrar o parse
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                return CorrectionResult(
                    is_correct=data.get("is_correct", False),
                    feedback=data.get("feedback", "Revise os cálculos."),
                    explanation=data.get("explanation", "")
                )
            raise ValueError("Bloco JSON não encontrado.")
        except Exception as e:
            logger.error(f"Erro ao processar JSON: {e} | Resposta bruta: {response_text}")
            return CorrectionResult(
                is_correct=False, 
                feedback="Erro ao processar a correção.", 
                explanation=response_text
            )
