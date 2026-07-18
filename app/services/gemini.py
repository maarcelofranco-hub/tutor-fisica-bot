import base64
import json
import logging
import re
import os

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from app.config import settings
from app.models.schemas import CorrectionResult
from app.database import SessionLocal, QuestionResolution
from app.services.resolution_generator import generate_two_column_image

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
            self.model = None
            logger.warning("GEMINI_API_KEY not set. Using mock correction mode.")

    async def get_or_create_resolution_image(self, question_id: str, question_text: str) -> str:
        db = SessionLocal()
        try:
            res = db.query(QuestionResolution).filter_by(question_id=question_id).first()
            if res and res.imagem_path and os.path.exists(res.imagem_path):
                return res.imagem_path

            prompt = f"""
            Resolva a questão de física como um professor. 
            Siga estritamente este formato:
            
            DADOS:
            [Linha 1]
            [Linha 2]
            
            RESOLUCAO:
            [Passo 1 em LaTeX]
            [Passo 2 em LaTeX]
            
            Exemplo:
            DADOS:
            v_0=0
            v=20 m/s
            a=2 m/s^2
            \\Delta S=?
            
            RESOLUCAO:
            v^2 = v_0^2 + 2 \\cdot a \\cdot \\Delta S
            20^2 = 0 + 2 \\cdot 2 \\cdot \\Delta S
            400 = 4 \\cdot \\Delta S
            \\Delta S = 100 m
            
            Questão: {question_text}
            """
            
            response = await self.model.generate_content_async(prompt)
            text = response.text
            
            parts = text.split("RESOLUCAO:")
            dados = parts[0].replace("DADOS:", "").strip()
            resolucao = parts[1].strip()
            
            os.makedirs("assets", exist_ok=True)
            path = f"assets/res_{question_id}.png"
            
            generate_two_column_image(dados, resolucao, path)
            
            new_res = QuestionResolution(
                question_id=question_id,
                resolucao_latex=resolucao,
                imagem_path=path
            )
            db.add(new_res)
            db.commit()
            return path
            
        except Exception as e:
            logger.error(f"Erro ao gerar imagem de resolução: {e}")
            return None
        finally:
            db.close()

    async def extract_text_from_image(self, image_bytes: bytes, mime_type: str) -> str:
        if not self.enabled:
            return "[modo teste] resposta extraida da imagem"
        prompt = "Extraia somente o conteudo escrito pelo aluno nesta imagem. Retorne apenas o texto."
        response = await self.model.generate_content_async(
            [prompt, {"mime_type": mime_type, "data": base64.b64encode(image_bytes).decode("utf-8")}]
        )
        return (response.text or "").strip()

    async def correct_answer(
        self, question_image_bytes: bytes | None, question_mime_type: str, 
        student_answer: str, answer_key: str | None = None,
    ) -> CorrectionResult:
        if not self.enabled:
            return CorrectionResult(is_correct=True, feedback="[Modo teste] Resposta recebida.", explanation=None)

        prompt = self._build_prompt(student_answer, answer_key)
        parts = [prompt]
        if question_image_bytes:
            parts.append({"mime_type": question_mime_type, "data": base64.b64encode(question_image_bytes).decode("utf-8")})

        try:
            response = await self.model.generate_content_async(parts)
            return self._parse_response(response.text or "", student_answer)
        except Exception:
            logger.exception("Gemini correction failed")
            return CorrectionResult(is_correct=False, feedback="Nao foi possivel corrigir agora.", explanation=None)

    def _build_prompt(self, student_answer: str, answer_key: str | None) -> str:
        key_section = f"GABARITO: {answer_key}." if answer_key else "Resolva com precisão técnica."
        return (
            f"Professor de Fisica. {key_section}\nResposta: {student_answer}\n"
            "Formato JSON: {'is_correct': bool, 'feedback': str, 'error': str|null, 'correct_answer': str, 'tip': str, 'steps': list}\n"
            "Use negrito *...* para cálculos. Use Δ."
        )

    def _parse_response(self, text: str, student_answer: str) -> CorrectionResult:
        cleaned = re.sub(r"^\x60{3}(?:json)?\s*", "", text.strip())
        cleaned = re.sub(r"\s*\x60{3}$", "", cleaned)
        try:
            payload = json.loads(cleaned)
            return CorrectionResult(
                is_correct=bool(payload.get("is_correct")),
                feedback=self._format_feedback(payload, student_answer),
                explanation=None
            )
        except:
            return CorrectionResult(is_correct=False, feedback="Erro na analise.", explanation=None)

    def _format_feedback(self, p: dict, student_answer: str) -> str:
        res = "Correto ✅" if p.get("is_correct") else "Incorreto ❌"
        lines = [f"📊 RESULTADO: {res}", f"📝 Resposta: {student_answer}", ""]
        if p.get("error"): lines.extend([f"❌ Erro: {p['error']}", ""])
        if p.get("steps"):
            lines.append("📖 Passo a passo:")
            for index, step in enumerate(p["steps"], start=1):
                lines.append(f"{index}. {str(step).strip()}")
        return "\n".join(lines)
