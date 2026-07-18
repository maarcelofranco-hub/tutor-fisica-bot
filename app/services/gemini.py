import base64
import json
import logging
import re
import os
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from app.config import settings
from app.database import SessionLocal, QuestionResolution
from app.services.resolution_generator import generate_latex_solution

logger = logging.getLogger(__name__)

class GeminiService:
    def __init__(self) -> None:
        self.enabled = bool(settings.gemini_api_key)
        if self.enabled:
            genai.configure(api_key=settings.gemini_api_key)
            model_name = settings.gemini_model
            if not model_name.startswith("models/"):
                model_name = f"models/{model_name}"
            self.model = genai.GenerativeModel(model_name)
        else:
            logger.warning("GEMINI_API_KEY not set. Gemini features disabled.")
            self.model = None

    async def get_or_create_resolution_image(self, question_id: str) -> str:
        """
        Gera a resolução em imagem apenas uma vez e salva no banco.
        """
        db = SessionLocal()
        try:
            resolution = db.query(QuestionResolution).filter(QuestionResolution.question_id == question_id).first()
            if resolution:
                return resolution.image_url
            
            # 1. Solicita o conteúdo estruturado ao Gemini
            prompt = f"Gere os dados e os passos (resolução) em LaTeX para a questão {question_id}. Responda estritamente neste formato:\nDADOS:\n[seus dados aqui]\nRESOLUÇÃO:\n[seus passos aqui]"
            response = self.model.generate_content(prompt)
            
            # 2. Faz o parsing simples do texto
            text = response.text
            data_match = re.search(r"DADOS:(.*?)(?=RESOLUÇÃO:|$)", text, re.S)
            res_match = re.search(r"RESOLUÇÃO:(.*)", text, re.S)
            
            data_str = data_match.group(1).strip() if data_match else "Sem dados"
            res_str = res_match.group(1).strip() if res_match else "Sem resolução"
            
            # 3. Define o caminho e chama o gerador com os 4 argumentos exigidos
            output_path = f"static/resolutions/{question_id}.png"
            await generate_latex_solution(question_id, data_str, res_str, output_path)
            
            # 4. Salva no banco de dados
            new_resolution = QuestionResolution(question_id=question_id, image_url=output_path)
            db.add(new_resolution)
            db.commit()
            return output_path
        finally:
            db.close()

    async def extract_text_from_image(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        if not self.enabled: return ""
        try:
            response = self.model.generate_content([
                {"mime_type": mime_type, "data": base64.b64encode(image_bytes).decode("utf-8")},
                "Extraia todo o texto e fórmulas matemáticas desta imagem com precisão."
            ])
            return response.text
        except Exception as e:
            logger.error(f"Erro no OCR Gemini: {e}")
            return ""

    async def correct_answer(self, student_text: str, question_id: str) -> str:
        """
        Compara o texto do aluno com a resolução da questão.
        """
        if not self.enabled: return "Erro: Serviço de correção indisponível."
        
        prompt = self._build_prompt_correction(student_text, question_id)
        try:
            response = self.model.generate_content(prompt)
            return self._format_feedback(response.text)
        except Exception as e:
            logger.error(f"Erro na correção: {e}")
            return "Não foi possível analisar sua resposta agora."

    def _build_prompt_correction(self, student_text: str, question_id: str) -> str:
        return f"""
        Você é um tutor de física. Analise a resposta do aluno abaixo comparando-a com a resolução correta da questão {question_id}.
        Resumo do que o aluno escreveu: {student_text}
        
        Forneça um feedback curto, encorajador, aponte erros se houver e diga se ele chegou ao resultado correto.
        """

    def _format_feedback(self, text: str) -> str:
        return text.strip()
