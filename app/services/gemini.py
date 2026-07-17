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

        # Mantendo 500 tokens para evitar que a resposta seja cortada
        response = client.models.generate_content(
            model=self.model_name, 
            contents=contents,
            config={"max_output_tokens": 500, "temperature": 0.1}
        )
        return self._parse_response(response.text or "", student_answer)

    def _build_prompt(self, student_answer: str, answer_key: str | None) -> str:
        return f"""
        Você é um assistente de física.
        Avalie a resposta: '{student_answer}'. Esperado: '{answer_key}'.
        
        Se a resposta estiver incorreta, forneça a resolução seguindo ESTRITAMENTE este formato:
        
        *DADOS*
        (Liste apenas variáveis: valores)
        
        *RESOLUÇÃO*
        (Apenas passos matemáticos, um por linha)
        
        *RESPOSTA*
        (Valor final com unidade)
        
        Retorne em JSON com as chaves: 
        - 'is_correct' (boolean)
        - 'feedback' (curtíssimo)
        - 'explanation' (o texto acima formatado)
        """

    def _parse_response(self, response_text: str, original_answer: str) -> CorrectionResult:
        try:
            # Remove blocos de markdown
            clean_text = re.sub(r'^```json\s*|\s*```$', '', response_text.strip(), flags=re.MULTILINE)
            
            # Tenta fechar JSONs incompletos
            if clean_text.count('{') > clean_text.count('}'):
                clean_text += '}'
                
            data = json.loads(clean_text)
            return CorrectionResult(
                is_correct=data.get("is_correct", False),
                feedback=data.get("feedback", "Corrigido."),
                explanation=data.get("explanation", "Sem detalhes.")
            )
        except Exception as e:
            logger.error(f"Erro no parse do JSON: {e} | Resposta original: {response_text}")
            
            # CAMADA DE SEGURANÇA: Se o JSON quebrar, enviamos o texto bruto
            # para que o aluno não receba a mensagem de "Erro ao processar"
            return CorrectionResult(
                is_correct=False,
                feedback="Aqui está a resolução:",
                explanation=response_text if len(response_text) > 5 else "Tente reenviar a resposta."
            )
