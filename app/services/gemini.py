import httpx
from app.config import settings
import json
import base64

class GeminiService:
    def __init__(self):
        self.api_key = settings.gemini_api_key
        # MUDANÇA AQUI: Trocamos "v1beta" por "v1" para usar a API oficial e estável
        self.url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={self.api_key}"

    async def correct_answer(self, question_image_bytes, question_mime_type, student_answer):
        # Converter os bytes da imagem para Base64 corretamente
        image_base64 = base64.b64encode(question_image_bytes).decode('utf-8')
        
        # Estrutura de dados para a API do Google
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
                            "data": image_base64
                        }
                    }
                ]
            }]
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.url, json=payload, timeout=30.0)
                
                # Proteção: Se o Google retornar um erro (como o 404 de antes), avisamos no log sem quebrar o bot
                if response.status_code != 200:
                    print(f"Erro da API do Google: Status {response.status_code} - {response.text}")
                    return {"is_correct": False, "feedback": "Erro na API", "explanation": "O servidor de IA está indisponível no momento."}

                result = response.json()
                
                # Extraindo o texto da resposta (agora é seguro pois sabemos que deu status 200)
                text = result['candidates'][0]['content']['parts'][0]['text']
                return json.loads(text.replace('```json', '').replace('```', '').strip())
            
            except Exception as e:
                print(f"Erro na chamada HTTP ou formatação JSON: {e}")
                return {"is_correct": False, "feedback": "Erro interno", "explanation": "Houve uma instabilidade, tente reenviar."}
