import httpx
from app.config import settings
import json
import base64

class GeminiService:
    def __init__(self):
        self.api_key = settings.gemini_api_key
        self.url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.api_key}"

    async def correct_answer(self, question_image_bytes, question_mime_type, student_answer):
        # 1. Converter os bytes da imagem para Base64 corretamente
        image_base64 = base64.b64encode(question_image_bytes).decode('utf-8')
        
        # 2. Estrutura de dados para a API do Google
        payload = {
            "contents": [{
                "parts": [
                    {
                        "text": f"""Você é um tutor de Física dedicado e didático.
Analise a questão e a resposta: {student_answer}

Utilize este método na sua explicação:
1. Identifique e converta unidades para o S.I.
2. Substitua os valores na fórmula.
3. Isole a incógnita.
4. Apresente o resultado.

Retorne APENAS um JSON com 'is_correct', 'feedback', 'explanation'."""
                    },
                    {
                        "inline_data": {
                            "mime_type": question_mime_type, 
                            "data": image_base64 # Aqui vai a imagem convertida
                        }
                    }
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
                print(f"Erro na chamada HTTP ou JSON: {e}")
                return {"is_correct": False, "feedback": "Erro interno", "explanation": "Houve uma instabilidade, tente reenviar."}
