from app.services.gemini import GeminiService
from app.config import settings
from google import genai

def selecionar_tema_por_input(input_aluno, temas_disponiveis):
    lista_formatada = ", ".join(temas_disponiveis)
    prompt = (
        f"O aluno quer estudar sobre '{input_aluno}'.\n"
        f"Os temas disponíveis no nosso banco de dados são: [{lista_formatada}].\n"
        "Regras:\n"
        "1. Se houver um tema que seja uma correspondência clara ou muito próxima, retorne APENAS o nome exato desse tema.\n"
        "2. Se o aluno pedir algo vago ou houver ambiguidade, peça educadamente para o aluno escolher entre os que melhor se aplicam.\n"
        "3. Mantenha a resposta curta."
    )
    
    # Criamos o cliente diretamente aqui para facilitar
    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=[prompt]
    )
    return response.text.strip()
