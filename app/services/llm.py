from app.services.gemini import GeminiService

# Instância do serviço para usar a mesma lógica que você já tem
gemini_service = GeminiService()

def selecionar_tema_por_input(input_aluno, temas_disponiveis):
    lista_formatada = ", ".join(temas_disponiveis)
    prompt = (
        f"O aluno quer estudar sobre '{input_aluno}'.\n"
        f"Os temas disponíveis no nosso banco de dados são: [{lista_formatada}].\n"
        "Regras:\n"
        "1. Se houver um tema que seja uma correspondência clara ou muito próxima, responda APENAS o nome exato desse tema.\n"
        "2. Se o aluno pedir algo vago ou houver dois temas que se encaixem (ex: 'cinemática' e existem 'MRU' e 'MRUV'), peça educadamente para o aluno escolher entre os que melhor se aplicam.\n"
        "3. Mantenha a resposta curta e direta."
    )
    
    # Chama o método que envia o prompt para o Gemini
    # Ajuste o nome do método caso o seu GeminiService tenha outro nome (ex: chat_with_gemini)
    return gemini_service.generate_content(prompt)
