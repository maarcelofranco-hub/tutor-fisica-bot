import google.generativeai as genai
from app.config import settings
import json

class GeminiService:
    def __init__(self):
        genai.configure(api_key=settings.gemini_api_key)
        
        self.system_instruction = """
Você é um tutor de Física dedicado, didático e profissional. 
Sua missão é corrigir as respostas dos alunos com base em imagens de questões e textos.

Ao apresentar a resolução de problemas de física, utilize sempre o seguinte método:
1. Primeiro, identifique e converta as unidades necessárias para o Sistema Internacional.
2. Substitua os valores numéricos conhecidos diretamente na fórmula original.
3. Em seguida, realize o isolamento algébrico da incógnita desejada.
4. Apresente o resultado final claramente com as unidades de medida corretas.

Use Markdown para destacar fórmulas (ex: use crases). 
Não utilize caracteres de escape como literal '\\n' na sua resposta JSON.
"""
        
        # Configuração do modelo utilizando a versão 2.5 Flash
        self.model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=self.system_instruction,
            generation_config={"response_mime_type": "application/json"}
        )

    async def correct_answer(self, question_image_bytes, question_mime_type, student_answer):
        prompt = f"""
        Analise a questão na imagem e a resposta do aluno abaixo.
        Resposta do aluno: {student_answer}
        
        Retorne um JSON com a seguinte estrutura:
        {{
            "is_correct": boolean,
            "feedback": "Mensagem curta de correção",
            "explanation": "Explicação detalhada seguindo o método didático definido"
        }}
        """

        response = await self.model.generate_content_async([
            {"mime_type": question_mime_type, "data": question_image_bytes},
            prompt
        ])
        
        return json.loads(response.text)
