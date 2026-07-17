import google.generativeai as genai
from app.config import settings
import json

class GeminiService:
    def __init__(self):
        # Configuração forçada da API para usar o endpoint estável v1
        # Isso impede que a biblioteca tente buscar o endpoint v1beta automaticamente
        genai.configure(
            api_key=settings.gemini_api_key,
            api_endpoint="https://generativelanguage.googleapis.com"
        )
        
        self.system_instruction = """
Você é um tutor de Física dedicado, didático e profissional. 
Sua missão é corrigir as respostas dos alunos com base em imagens de questões e textos.

Ao apresentar a resolução de problemas de física, utilize sempre o seguinte método:
1. Primeiro, identifique e converta as unidades necessárias para o Sistema Internacional.
2. Substitua os valores numéricos conhecidos diretamente na fórmula original.
3. Em seguida, realize o isolamento algébrico da incógnita desejada.
4. Apresente o resultado final claramente com as unidades de medida corretas.

Use Markdown para destacar fórmulas (ex: use crases).
"""
        
        # Nome do modelo com prefixo 'models/' para forçar o caminho estável
        self.model = genai.GenerativeModel(
            model_name="models/gemini-1.5-flash",
            system_instruction=self.system_instruction,
            generation_config={"response_mime_type": "application/json"}
        )

    async def correct_answer(self, question_image_bytes, question_mime_type, student_answer):
        prompt = f"""
        Analise a questão na imagem e a resposta do aluno abaixo.
        Resposta do aluno: {student_answer}
        
        Retorne um JSON contendo exatamente as chaves: "is_correct", "feedback", "explanation".
        """

        try:
            response = await self.model.generate_content_async([
                {"mime_type": question_mime_type, "data": question_image_bytes},
                prompt
            ])
            
            # Limpeza básica do texto retornado pelo modelo
            raw_text = response.text.replace('```json', '').replace('```', '').strip()
            data = json.loads(raw_text)
            
            # Validação de segurança para garantir que o dicionário tenha os campos esperados
            if isinstance(data, dict) and 'feedback' in data:
                return data
            else:
                return {"is_correct": False, "feedback": "Erro de formato", "explanation": "A resposta não está no formato correto."}
        
        except Exception as e:
            print(f"Erro na execução da chamada Gemini: {e}")
            return {"is_correct": False, "feedback": "Erro interno", "explanation": "Tente novamente em breve."}
