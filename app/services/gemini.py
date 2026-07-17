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
        Você é um professor de física renomado. Avalie a resposta: '{student_answer}'. Gabarito: '{answer_key}'.
        
        Se incorreta, forneça a resolução completa com a elegância e clareza de um LIVRO DIDÁTICO seguindo estas regras:
        
        1. FORMATAÇÃO: Use *negrito* para títulos e seções. Pule UMA LINHA entre cada linha de cálculo para manter a organização.
        
        2. REGRA DE OURO (SEM UNIDADES): Durante a manipulação algébrica e substituição numérica, NÃO utilize unidades de medida (m, s, kg, J). Trabalhe apenas com os números.
        
        3. NOTAÇÃO MATEMÁTICA FORMAL:
           - NÃO utilize 'sqrt' ou '^2'. 
           - Use o símbolo de raiz quadrada "√".
           - Use o sobrescrito "²" para potências (exemplo: v²).
           - Exemplo de estilo:
             v² = 2 * g * h
             v = √49
             v = 7
        
        4. RESULTADO: Apenas na conclusão final da resolução, apresente o resultado acompanhado da unidade de medida correta.
        
        Retorne APENAS um objeto JSON, com estas chaves:
        "is_correct": boolean,
        "feedback": "comentário curto",
        "explanation": "Resolução detalhada seguindo o padrão de livro didático."
        """

    def _parse_response(self, response_text: str, original_answer: str) -> CorrectionResult:
        try:
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
