import google.generativeai as genai
from app.config import settings
import json

class GeminiService:
    def __init__(self):
        # Configuração básica recomendada
        genai.configure(api_key=settings.gemini_api_key)
        
        self.system_instruction = """
Você é um tutor de Física dedicado, didático e profissional.
Sua missão é corrigir as respostas dos alunos com base em imagens de questões e textos.
"""
        # Usando a forma padrão de inicialização
        self.model = genai.GenerativeModel("gemini-1.5-flash")

    async def correct_answer(self, question_image_bytes, question_mime_type, student_answer):
        prompt = f"Analise a questão e a resposta: {student_answer}. Retorne JSON com 'is_correct', 'feedback', 'explanation'."

        try:
            # Chamada simplificada
            response = await self.model.generate_content_async([
                {"mime_type": question_mime_type, "data": question_image_bytes},
                prompt
            ])
            return json.loads(response.text.replace('```json', '').replace('```', ''))
        except Exception as e:
            print(f"Erro: {e}")
            return {"is_correct": False, "feedback": "Erro", "explanation": "Tente de novo."}
