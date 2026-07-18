import base64
import json
import logging
import re
import os

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from app.config import settings
from app.models.schemas import CorrectionResult

# Importamos o banco de dados e a classe de resolução que você criou
from app.database import SessionLocal, QuestionResolution
# Importamos a função que desenha o layout que você validou (2 colunas)
from app.services.resolution_generator import generate_two_column_image

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

    # ==========================================
    # NOVO: FLUXO DE RESOLUÇÃO DE ELITE (IMAGEM)
    # ==========================================
    async def get_or_create_resolution_image(self, question_id: str, question_text: str) -> str:
        """
        Gera ou recupera a imagem de resolução da questão no formato 2 colunas.
        """
        db = SessionLocal()
        try:
            # 1. Verifica se já existe a imagem pronta no banco de dados
            res = db.query(QuestionResolution).filter_by(question_id=question_id).first()
            if res and res.imagem_path and os.path.exists(res.imagem_path):
                logger.info(f"Imagem recuperada do cache: {res.imagem_path}")
                return res.imagem_path

            # 2. Se não existir, pede ao Gemini a estrutura validada
            prompt = f"""
            Resolva a questão de física como um professor. 
            Sua resposta será convertida em uma imagem de duas colunas.
            
            Siga estritamente este formato:
            
            DADOS:
            [Linha 1]
            [Linha 2]
            
            RESOLUCAO:
            [Passo 1 em LaTeX]
            [Passo 2 em LaTeX]
            
            Exemplo de formato esperado:
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
            
            # Chama a API de forma assíncrona
            response = await self.model.generate_content_async(prompt)
            text = response.text
            
            # 3. Faz o parser dividindo nos blocos que definimos
            parts = text.split("RESOLUCAO:")
            dados = parts[0].replace("DADOS:", "").strip()
            resolucao = parts[1].strip()
            
            # Garante que a pasta assets existe
            os.makedirs("assets", exist_ok=True)
            path = f"assets/res_{question_id}.png"
            
            # 4. Gera a imagem usando a função do matplotlib
            generate_two_column_image(dados, resolucao, path)
            
            # 5. Salva no banco de dados
            new_res = QuestionResolution(
                question_id=question_id,
                resolucao_latex=resolucao,
                imagem_path=path
            )
            db.add(new_res)
            db.commit()
            
            logger.info(f"Nova imagem gerada e salva: {path}")
            return path
            
        except Exception as e:
            logger.error(f"Erro ao gerar imagem de resolução: {e}")
            return None
        finally:
            db.close()

    # ==========================================
    # FLUXO ANTIGO MANTIDO (CORREÇÃO DE TEXTO)
    # ==========================================
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
            "- Matemática padrão BR: use vírgula para decimais (ex: 6,72) e ponto para multiplicação (ex: 200 . 4). NUNCA use asterisco (*) para multiplicar.\n"
            "- Use o símbolo Δ para variações (ex: ΔT).\n"
            "- USE formatação em negrito (asteriscos `*`) APENAS para destacar cada linha de cálculo, fórmula ou dados, fechando o asterisco linha a linha. Exemplo: *v = 15 m/s* ou *v² = v_0² + 2 . a . ΔS*.\n"
            "- ESTRUTURA DOS PASSOS (MUITO IMPORTANTE):\n"
            "  1. O passo de 'Dados' DEVE ter cada informação em uma linha diferente, usando a quebra de linha (\\n) dentro da string do JSON.\n"
            "  2. O passo de 'Cálculos' DEVE agrupar TODA a evolução algébrica em um ÚNICO passo. Use a quebra de linha (\\n) para separar cada etapa da equação, sem criar novos passos no array.\n"
            "- Retorne APENAS JSON valido com os campos:\n"
            '  {"is_correct": true|false, "feedback": "texto curto", "error": "onde errou ou null", '
            '"correct_answer": "resposta correta", "tip": "dica objetiva", '
            '"steps": ["Dados:\\n*v_0 = 0 m/s*\\n*v = 15 m/s*\\n*ΔS = 0,75 m*", "Conversão de unidades:\\n*v = 54 / 3,6 = 15 m/s*", "Fórmula de Torricelli:\\n*v² = v_0² + 2 . a . ΔS*", "Resolução:\\n*15² = 0² + 2 . a . 0,75*\\n*225 = 1,5 . a*\\n*a = 225 / 1,5*\\n*a = 150 m/s²*"]}\n'
        )

    def _parse_response(self, text: str, student_answer: str) -> CorrectionResult:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            # Substituição segura das crases para não quebrar a cópia do código
            cleaned = re.sub(r"^\x60{3}(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*\x60{3}$", "", cleaned)
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
            for index, step in enumerate(steps,
