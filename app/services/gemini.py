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

# Importamos o question_provider para o Gemini ler o enunciado real e não inventar respostas
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
        Gera a resolução em imagem apenas uma vez e salva no banco/tmp.
        """
        db = SessionLocal()
        try:
            resolution = db.query(QuestionResolution).filter(QuestionResolution.question_id == question_id).first()
            if resolution:
                return resolution.image_url
            
            # Busca o texto real da questão para enviar ao Gemini
            enunciado = "Enunciado não encontrado. Resolva baseando-se apenas nos seus conhecimentos."
            for topic in question_provider.list_topics():
                for q in question_provider.list_questions(topic):
                    if q.id == question_id:
                        # Pega o texto da questão (ajuste '.name' se o texto completo ficar em outro atributo)
                        enunciado = getattr(q, 'name', '') or getattr(q, 'text', '')
                        break

            # 1. O SUPER PROMPT DE RESOLUÇÃO (Regras estritas de LaTeX)
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
            
            # 2. Faz o parsing simples do texto
            text = response.text
            data_match = re.search(r"DADOS:(.*?)(?=RESOLUÇÃO:|$)", text, re.S)
            res_match = re.search(r"RESOLUÇÃO:(.*)", text, re.S)
            
            # Limpa quebras de linha para evitar buracos na imagem
            data_str = data_match.group(1).strip() if data_match else "Sem dados"
            res_str = res_match.group(1).strip() if res_match else "Sem resolução"
            
            # 3. Define o caminho e chama o gerador de imagem (Pasta TMP para o Render!)
            output_path = f"/tmp/{question_id}_res.png"
            await generate_latex_solution(question_id, data_str, res_str, output_path)
            
            # 4. Salva no banco de dados
            new_resolution = QuestionResolution(question_id=question_id, image_url=output_path)
            db.add(new_resolution)
            db.commit()
            
            logger.info(f"Nova resolução gerada e salva com sucesso: {output_path}")
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
        Você é um tutor de física empático e direto. Analise a resposta do aluno abaixo comparando-a com a resolução correta da questão {question_id}.
        Resumo do que o aluno escreveu: {student_text}
        
        Forneça um feedback curto (máximo 3 linhas), encorajador, aponte o erro principal (se houver) e diga claramente se ele acertou ou errou.
        """

    def _format_feedback(self, text: str) -> str:
        return text.strip()
