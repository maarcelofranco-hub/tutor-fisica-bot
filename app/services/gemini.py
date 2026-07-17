import google.generativeai as genai
from app.config import settings
import json

class GeminiService:
    def __init__(self):
        genai.configure(api_key=settings.gemini_api_key)
        
        # Esta é a instrução que dita o comportamento didático do seu tutor
        self.system_instruction = """
Você é um tutor de Física dedicado, didático e profissional. 
Sua missão é corrigir as respostas dos alunos com base em imagens de questões e textos.

Ao apresentar a resolução de problemas de física, utilize sempre o seguinte método:
1. Primeiro, identifique e converta as unidades necessárias para o Sistema Internacional.
2. Substitua os valores numéricos conhecidos diretamente na fórmula original.
3. Em seguida, realize o isolamento algébrico da incógnita desejada.
4. Apresente o resultado final claramente com as unidades de medida corretas.

Use Markdown para destacar fórmulas e resultados (ex: use crases para fórmulas). 
Não utilize caracteres de escape como literal '\\n' na sua resposta JSON, 
pois o sistema fará o processamento necessário.
"""
        
        # Configuração do modelo (usando o Flash conforme recomendado)
        self.model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            system_instruction=self.system_instruction,
            generation_config={"response_mime_type": "application/json"}
        )

    async def correct_answer(self, question_image_bytes, question_mime_type, student_answer):
        # Definição da estrutura JSON que o seu código espera
        prompt = f"""
        Analise a questão na imagem e a resposta do aluno abaixo.
        Resposta do aluno: {student_answer}
        
        Retorne um JSON com a seguinte estrutura:
        {{
            "is_correct": boolean,
            "feedback": "Mensagem curta de correção",
            "explanation": "Explicação detalhada seguindo a metodologia didática definida nas instruções do sistema"
        }}
        """

        response = await self.model.generate_content_async([
            {"mime_type": question_mime_type, "data": question_image_bytes},
            prompt
        ])
        
        # Converte a resposta JSON em um objeto Python
        return json.loads(response.text)
