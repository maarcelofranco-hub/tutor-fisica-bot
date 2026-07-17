import httpx
from app.config import settings
import json

class GeminiService:
    def __init__(self):
        self.api_key = settings.gemini_api_key
        self.url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.api_key}"

    async def correct_answer(self, question_image_bytes, question_mime_type, student_answer):
        # Estrutura de dados para a API do Google
        payload = {
            "contents": [{
                "parts": [
                    {"text": f"Analise a questão e a resposta: {student_answer}. Retorne JSON com 'is_correct', 'feedback', 'explanation'."},
                    {"inline_data": {"mime_type": question_mime_type, "data": question_image_bytes.decode('utf-8')}} # Certifique-se que o bytes já esteja em base64 aqui
                ]
            }]
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.url, json=payload, timeout=30.0)
                result = response.json()
                
                # Extraindo o texto da resposta
                text = result['candidates'][0]['content']['parts'][0]['text']
                return json.loads(text.replace('```json', '').replace('```', '').strip())
            
            except Exception as e:
                print(f"Erro na chamada HTTP: {e}")
                return {"is_correct": False, "feedback": "Erro", "explanation": "Tente novamente."}
