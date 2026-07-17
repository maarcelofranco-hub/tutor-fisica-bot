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

        response = client.models.generate_content(model=self.model_name, contents=contents)
        return self._parse_response(response.text or "", student_answer)

    def _build_prompt(self, student_answer: str, answer_key: str | None) -> str:
        return f"""
        Você é um professor de física didático.
        O aluno respondeu: '{student_answer}'.
        A resposta correta esperada é: '{answer_key}'.
        
        Sua tarefa é avaliar a resposta:
        1. Se estiver correta, parabenize-o de forma motivadora.
        2. Se estiver incorreta, forneça a resolução seguindo ESTRITAMENTE este padrão:
        
        - DADOS: Liste as variáveis fornecidas no problema (ex: v₀ = 0, g = 10 m/s², h = 20 m).
        - FÓRMULA: Escreva a fórmula principal que será utilizada, usando notação clara (ex: v² = v₀² + 2.g.Δh).
        - RESOLUÇÃO: Mostre o passo a passo dos cálculos até chegar ao resultado final.
        
        REGRAS DE FORMATAÇÃO:
        - Use caracteres Unicode para expoentes (ex: m/s², m²).
        - Mantenha tudo legível para WhatsApp.
        
        Retorne a resposta EXCLUSIVAMENTE em formato JSON com as chaves:
        - 'is_correct' (boolean)
        - 'feedback' (string curta e motivadora)
        - 'explanation' (string com a resolução no padrão solicitado)
        """

    def _parse_response(self, response_text: str, original_answer: str) -> CorrectionResult:
        try:
            clean_text = re.sub(r'^```json\s*|\s*```$', '', response_text.strip(), flags=re.MULTILINE)
            data = json.loads(clean_text)
            return CorrectionResult(
                is_correct=data.get("is_correct", False),
                feedback=data.get("feedback", "Sem feedback"),
                explanation=data.get("explanation", "")
            )
        except Exception as e:
            logger.error(f"Erro ao processar resposta do Gemini: {e}")
            return CorrectionResult(is_correct=False, feedback="Erro ao processar correção.", explanation=f"O modelo retornou: {response_text}")
