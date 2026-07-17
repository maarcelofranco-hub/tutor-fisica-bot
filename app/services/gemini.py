import base64
import json
import logging
import re

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from app.config import settings
from app.models.schemas import CorrectionResult

logger = logging.getLogger(__name__)


class GeminiService:
    def __init__(self) -> None:
        self.enabled = bool(settings.gemini_api_key)
        if self.enabled:
            # Configuração da API
            genai.configure(api_key=settings.gemini_api_key)
            
            # Garante que o modelo use o prefixo 'models/' para evitar o erro 404 de endpoint
            model_name = settings.gemini_model
            if not model_name.startswith("models/"):
                model_name = f"models/{model_name}"
                
            self.model = genai.GenerativeModel(model_name)
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

        try:
            response = await self.model.generate_content_async(parts)
            return self._parse_response(response.text or "", student_answer)
        except google_exceptions.ResourceExhausted:
            logger.warning("Gemini quota exceeded")
            return CorrectionResult(
                is_correct=False,
                feedback=(
                    "A correcao automatica esta temporariamente indisponivel "
                    "(limite diario da API Gemini atingido). "
                    "Sua resposta foi recebida. Tente novamente em alguns minutos "
                    "ou amanha. Para continuar estudando, envie o nome de outro tema."
                ),
                explanation=None,
            )
        except Exception:
            logger.exception("Gemini correction failed")
            return CorrectionResult(
                is_correct=False,
                feedback=(
                    "Nao foi possivel corrigir agora. Sua resposta foi recebida. "
                    "Tente novamente em instantes ou envie outro tema."
                ),
                explanation=None,
            )

    def _build_prompt(self, student_answer: str, answer_key: str | None) -> str:
        # Reforço crítico para garantir que a IA respeite estritamente o gabarito oficial
        key_section = (
            f"GABARITO OFICIAL: {answer_key}. \nATENÇÃO MÁXIMA: A sua correção DEVE corresponder exata e estritamente a este gabarito oficial. Sob nenhuma hipótese forneça uma correção que discorde desta chave de resposta."
            if answer_key
            else "Nao ha gabarito cadastrado. Resolva a questao a partir do enunciado com extrema precisão técnica."
        )
        
        return (
            "Voce e um professor de Fisica do ensino medio corrigindo a resposta de um aluno brasileiro no WhatsApp.\n"
            f"{key_section}\n"
            f"Resposta do aluno: {student_answer}\n\n"
            "Instrucoes CRÍTICAS de formatação para WhatsApp:\n"
            "- Responda em portugues brasileiro, tom didatico e direto.\n"
            "- No campo 'steps', NÃO coloque números no início das frases. O sistema já enumera automaticamente.\n"
            "- Abrevie os subscritos (ex: 'm_p' em vez de 'm_pessoa').\n"
            "- Matemática padrão BR: use vírgula para decimais (ex: 6,72) e ponto para multiplicação (ex: 200 . 4). NUNCA use asterisco (*).\n"
            "- Use o símbolo Δ para variações (ex: ΔT).\n"
            "- NÃO USE asteriscos (*) para negrito. Escreva o texto e as fórmulas normalmente sem marcações.\n"
            "- ESTRUTURA DOS PASSOS (MUITO IMPORTANTE):\n"
            "  1. O passo de 'Dados' DEVE ter cada informação em uma linha diferente, usando a quebra de linha (\\n) dentro da string do JSON.\n"
            "  2. O passo de 'Cálculos' DEVE agrupar TODA a evolução algébrica em um ÚNICO passo. Use a quebra de linha (\\n) para separar cada etapa da equação, sem criar novos passos no array.\n"
            "- Retorne APENAS JSON valido com os campos:\n"
            '  {"is_correct": true|false, "feedback": "texto curto", "error": "onde errou ou null", '
            '"correct_answer": "resposta correta", "tip": "dica objetiva", '
            '"steps": ["Dados:\\nv_0 = 0 m/s\\nv = 15 m/s\\nΔS = 0,75 m", "Fórmula: v² = v_0² + 2 . a . ΔS", "Resolução:\\n15² = 0² + 2 . a . 0,75\\n225 = 1,5 . a\\na = 225 / 1,5\\na = 150 m/s²"]}\n'
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
                lines.append("") # Respiro entre os passos principais

        if feedback and (is_correct or not error):
            lines.extend(["📚 Comentario:", feedback.strip(), ""])

        lines.append("━━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines).strip()
