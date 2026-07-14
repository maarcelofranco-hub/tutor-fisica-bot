import base64
import json
import logging
import re

import google.generativeai as genai

from app.config import settings
from app.models.schemas import CorrectionResult

logger = logging.getLogger(__name__)


class GeminiService:
    def __init__(self) -> None:
        self.enabled = bool(settings.gemini_api_key)
        if self.enabled:
            genai.configure(api_key=settings.gemini_api_key)
            self.model = genai.GenerativeModel(settings.gemini_model)
        else:
            self.model = None
            logger.warning("GEMINI_API_KEY not set. Using mock correction mode.")

    async def extract_text_from_image(self, image_bytes: bytes, mime_type: str) -> str:
        if not self.enabled:
            return "[modo teste] resposta extraida da imagem"
        prompt = (
            "Extraia somente o conteudo escrito pelo aluno nesta imagem de resposta. "
            "Retorne apenas o texto encontrado."
        )
        response = await self.model.generate_content_async(
            [
                prompt,
                {"mime_type": mime_type, "data": base64.b64encode(image_bytes).decode("utf-8")},
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
                feedback=self._format_feedback(
                    is_correct=True,
                    student_answer=student_answer,
                    feedback="[Modo teste] Resposta recebida.",
                    error=None,
                    correct_answer=None,
                    tip=None,
                    steps=None,
                ),
                explanation=None,
            )

        prompt = self._build_prompt(student_answer, answer_key)
        parts: list = [prompt]
        if question_image_bytes:
            parts.append(
                {
                    "mime_type": question_mime_type,
                    "data": base64.b64encode(question_image_bytes).decode("utf-8"),
                }
            )

        response = await self.model.generate_content_async(parts)
        return self._parse_response(response.text or "", student_answer)

    def _build_prompt(self, student_answer: str, answer_key: str | None) -> str:
        key_section = (
            f"Gabarito cadastrado: {answer_key}"
            if answer_key
            else "Nao ha gabarito cadastrado. Resolva a questao a partir do enunciado."
        )
        return (
            "Voce e um professor de Fisica do ensino medio corrigindo a resposta de um aluno brasileiro.\n"
            f"{key_section}\n"
            f"Resposta do aluno: {student_answer}\n\n"
            "Instrucoes:\n"
            "- Responda em portugues brasileiro, tom didatico e claro.\n"
            "- Seja detalhado, com passos numerados quando util.\n"
            "- Retorne APENAS JSON valido com os campos:\n"
            '  {"is_correct": true|false, "feedback": "texto curto", "error": "onde errou ou null", '
            '"correct_answer": "resposta correta", "tip": "dica objetiva", '
            '"steps": ["passo 1", "passo 2"]}\n'
        )

    def _parse_response(self, text: str, student_answer: str) -> CorrectionResult:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            payload = json.loads(cleaned)
            is_correct = bool(payload.get("is_correct"))
            feedback = self._format_feedback(
                is_correct=is_correct,
                student_answer=student_answer,
                feedback=str(payload.get("feedback", "Correcao concluida.")),
                error=payload.get("error"),
                correct_answer=payload.get("correct_answer"),
                tip=payload.get("tip"),
                steps=payload.get("steps") if isinstance(payload.get("steps"), list) else None,
            )
            return CorrectionResult(is_correct=is_correct, feedback=feedback, explanation=None)
        except json.JSONDecodeError:
            fallback = cleaned[:900] if cleaned else "Nao foi possivel analisar a resposta."
            return CorrectionResult(is_correct=False, feedback=fallback, explanation=None)

    def _format_feedback(
        self,
        is_correct: bool,
        student_answer: str,
        feedback: str,
        error: str | None,
        correct_answer: str | None,
        tip: str | None,
        steps: list | None,
    ) -> str:
        if settings.gemini_correction_style.lower() != "detailed":
            return feedback

        result_label = "Correto ✅" if is_correct else "Incorreto ❌"
        lines = [
            "━━━━━━━━━━━━━━━━━━━━",
            f"📊 RESULTADO: {result_label}",
            "",
            "📝 Sua resposta:",
            student_answer.strip() or "(nao informada)",
            "",
        ]

        if not is_correct and error:
            lines.extend(["❌ Onde errou:", str(error).strip(), ""])

        if correct_answer:
            lines.extend(["✅ Resposta correta:", str(correct_answer).strip(), ""])

        if tip:
            lines.extend(["💡 Dica:", str(tip).strip(), ""])

        if steps:
            lines.append("📖 Passo a passo:")
            for index, step in enumerate(steps, start=1):
                lines.append(f"{index}. {str(step).strip()}")
            lines.append("")

        if feedback and (is_correct or not error):
            lines.extend(["📚 Comentario:", feedback.strip(), ""])

        lines.append("━━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines).strip()
