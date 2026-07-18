import logging
import re
import os
import google.generativeai as genai

from app.config import settings
from app.database import SessionLocal, QuestionResolution
from app.services.resolution_generator import generate_latex_solution
from app.services.question_provider import question_provider

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
        Gera a resolução com custo ZERO em deploys:
        Se a imagem existe, retorna. Se não, mas o texto existe, regenera localmente!
        """
        db = SessionLocal()
        try:
            # Caminho consistente para a imagem
            output_path = f"/tmp/{question_id.split('/')[-1].split('.')[0]}_res.png"
            resolution = db.query(QuestionResolution).filter(QuestionResolution.question_id == question_id).first()
            
            # ========================================================
            # 🛡️ BLINDAGEM DE TOKENS (CUSTO ZERO NO DEPLOY)
            # ========================================================
            if resolution:
                if os.path.exists(output_path):
                    return output_path
                else:
                    # Foto apagada no deploy? Regenera localmente (sem custo de API!)
                    logger.info(f"Foto apagada no deploy. Regenerando localmente para: {question_id}")
                    await generate_latex_solution(
                        question_id, 
                        resolution.dados_latex or "Sem dados", 
                        resolution.resolucao_latex or "Sem resolucao", 
                        output_path
                    )
                    return output_path
            
            # ========================================================
            # GERAÇÃO PELA API (APENAS QUESTÕES NOVAS)
            # ========================================================
            enunciado = "Resolva esta questão de física."
            # Busca enunciado real no question_provider
            for topic in question_provider.list_topics():
                for q in question_provider.list_questions(topic):
                    if q.id == question_id:
                        enunciado = getattr(q, 'name', '') or getattr(q, 'text', '')
                        break

            prompt = f"""Você é um professor de Física de excelência. Sua tarefa é criar uma resolução passo a passo detalhada e definitiva para a questão fornecida.

REGRAS DE FORMATAÇÃO (MUITO IMPORTANTE):
O seu retorno será lido por um script Python que colocará cada linha da sua resposta dentro de um ambiente matemático LaTeX. Portanto:
1. NÃO use os delimitadores $ ou $$ na sua resposta. O sistema Python já fará isso automaticamente.
2. Se precisar escrever palavras normais ou explicações curtas, envolva-as OBRIGATORIAMENTE em \\text{{...}} (ex: \\text{{Substituindo os valores:}} ).
3. Cada quebra de linha será renderizada como uma linha nova na imagem final. Portanto, pule linha entre os passos.

ESTRUTURA OBRIGATÓRIA (Responda estritamente com estas duas palavras-chave):
DADOS:
- Liste linha por linha os dados numéricos extraídos do enunciado usando a notação correta (ex: v_0 = 10 \\text{{ m/s}}). Não use marcadores como '-' ou '*' no início das linhas.

RESOLUÇÃO:
- Linha 1: Apresente SEMPRE a fórmula principal literal (ex: F_r = m \\cdot a).
- Linhas seguintes: Mostre a substituição dos valores passo a passo, linha por linha, sem pular etapas algébricas.
- Última linha: Destaque o resultado final com a unidade de medida correta no Sistema Internacional (ex: v = 25 \\text{{ m/s}}).

QUESTÃO A SER RESOLVIDA:
{enunciado}
"""
            
            response = self.model.generate_content(prompt)
            text = response.text
            
            data_match = re.search(r"DADOS:(.*?)(?=RESOLUÇÃO:|$)", text, re.S)
            res_match = re.search(r"RESOLUÇÃO:(.*)", text, re.S)
            
            data_str = data_match.group(1).strip() if data_match else "Sem dados"
            res_str = res_match.group(1).strip() if res_match else "Sem resolução"
            
            # Gera imagem pela primeira vez
            await generate_latex_solution(question_id, data_str, res_str, output_path)
            
            # Salva TEXTO no banco para nunca mais gastar tokens!
            new_resolution = QuestionResolution(
                question_id=question_id, 
                dados_latex=data_str,
                resolucao_latex=res_str,
                image_url=output_path
            )
            db.add(new_resolution)
            db.commit()
            
            logger.info(f"Nova resolução gerada (Gemini) e salva com sucesso: {output_path}")
            return output_path
        finally:
            db.close()

    async def extract_text_from_image(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        if not self.enabled: return ""
        try:
            import base64
            response = self.model.generate_content([
                {"mime_type": mime_type, "data": base64.b64encode(image_bytes).decode("utf-8")},
                "Extraia todo o texto e fórmulas matemáticas desta imagem com precisão."
            ])
            return response.text
        except Exception as e:
            logger.error(f"Erro no OCR Gemini: {e}")
            return ""

    async def correct_answer(self, student_text: str, question_id: str) -> str:
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
        Você é um tutor de física empático e direto. Analise a resposta do aluno abaixo comparando-a com a resolução correta da questão {question_id}.
        Resumo do que o aluno escreveu: {student_text}
        
        Forneça um feedback curto (máximo 3 linhas), encorajador, aponte o erro principal (se houver) e diga claramente se ele acertou ou errou.
        """

    def _format_feedback(self, text: str) -> str:
        return text.strip()
