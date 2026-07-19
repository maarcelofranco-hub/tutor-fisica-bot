import logging
import re
import os
from google import genai

from app.config import settings
from app.database import SessionLocal, QuestionResolution
from app.services.resolution_generator import generate_latex_solution
from app.services.question_provider import question_provider

logger = logging.getLogger(__name__)

class GeminiService:
    def __init__(self) -> None:
        self.enabled = bool(settings.gemini_api_key)
        if self.enabled:
            self.client = genai.Client(api_key=settings.gemini_api_key)
            self.model_name = settings.gemini_model
        else:
            logger.warning("GEMINI_API_KEY not set. Gemini features disabled.")
            self.client = None

    async def get_or_create_resolution_image(self, question_id: str) -> str:
        db = SessionLocal()
        try:
            output_path = f"/tmp/{question_id.split('/')[-1].split('.')[0]}_res.png"
            resolution = db.query(QuestionResolution).filter(QuestionResolution.question_id == question_id).first()
            
            if resolution:
                if os.path.exists(output_path):
                    return output_path
                else:
                    logger.info(f"Foto apagada no deploy. Regenerando localmente para: {question_id}")
                    await generate_latex_solution(
                        question_id, 
                        resolution.dados_latex or "Sem dados", 
                        resolution.resolucao_latex or "Sem resolucao", 
                        output_path
                    )
                    return output_path
            
            enunciado = "Resolva esta questão de física."
            for topic in question_provider.list_topics():
                for q in question_provider.list_questions(topic):
                    if q.id == question_id:
                        enunciado = getattr(q, 'name', '') or getattr(q, 'text', '')
                        break

            prompt = f"""Você é um professor de Física de excelência. Sua tarefa é criar uma resolução passo a passo detalhada e definitiva para a questão fornecida.

REGRAS DE FORMATAÇÃO:
1. NÃO use os delimitadores $ ou $$ na sua resposta. 
2. Se precisar escrever explicações, envolva-as em \\text{{...}}.
3. Pule linha entre os passos.

ESTRUTURA:
DADOS:
- Liste os dados (ex: v_0 = 10 \\text{{ m/s}}).

RESOLUÇÃO:
- Linha 1: Fórmula principal literal.
- Linhas seguintes: Substituição passo a passo.
- Última linha: Resultado final com unidade.

QUESTÃO:
{enunciado}
"""
            
            response = self.client.models.generate_content(model=self.model_name, contents=prompt)
            text = response.text
            
            data_match = re.search(r"DADOS:(.*?)(?=RESOLUÇÃO:|$)", text, re.S)
            res_match = re.search(r"RESOLUÇÃO:(.*)", text, re.S)
            
            data_str = data_match.group(1).strip() if data_match else "Sem dados"
            res_str = res_match.group(1).strip() if res_match else "Sem resolução"
            
            await generate_latex_solution(question_id, data_str, res_str, output_path)
            
            new_resolution = QuestionResolution(
                question_id=question_id, 
                dados_latex=data_str,
                resolucao_latex=res_str,
                image_url=output_path
            )
            db.add(new_resolution)
            db.commit()
            
            logger.info(f"Nova resolução gerada e salva: {output_path}")
            return output_path
        finally:
            db.close()

    async def extract_text_from_image(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        if not self.enabled: return ""
        try:
            import base64
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[
                    {"mime_type": mime_type, "data": base64.b64encode(image_bytes).decode("utf-8")},
                    "Extraia todo o texto e fórmulas desta imagem com precisão."
                ]
            )
            return response.text
        except Exception as e:
            logger.error(f"Erro no OCR Gemini: {e}")
            return ""

    async def correct_answer(self, student_text: str, question_id: str) -> str:
        if not self.enabled: return "Erro: Serviço de correção indisponível."
        
        prompt = self._build_prompt_correction(student_text, question_id)
        try:
            response = self.client.models.generate_content(model=self.model_name, contents=prompt)
            return self._format_feedback(response.text)
        except Exception as e:
            logger.error(f"Erro na correção: {e}")
            return "Não foi possível analisar sua resposta agora."

    def _build_prompt_correction(self, student_text: str, question_id: str) -> str:
        return f"Você é um tutor de física. Analise a resposta do aluno: {student_text} para a questão {question_id}. Feedback curto, encorajador e aponte se acertou/errou."

    def _format_feedback(self, text: str) -> str:
        return text.strip()
