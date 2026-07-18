import logging
from app.services.message_sender import MessageSender
# Importe aqui outros serviços necessários, ex: a lógica de processamento de IA

logger = logging.getLogger(__name__)

async def handle_message(data: dict, sender: MessageSender):
    """
    Função principal que processa as mensagens recebidas do webhook.
    """
    logger.info("Iniciando processamento da mensagem...")
    
    try:
        # Aqui você coloca a lógica que extrai o texto/imagem da mensagem
        # e decide o que responder usando o 'sender' (instância do MessageSender).
        
        # Exemplo básico de estrutura:
        # 1. Identificar o remetente
        # 2. Verificar se é texto ou imagem
        # 3. Chamar o serviço de IA ou lógica de física
        # 4. Enviar a resposta via sender.send_text() ou sender.send_question_image()
        
        logger.info("Mensagem processada com sucesso.")
        
    except Exception as e:
        logger.error("Erro ao processar mensagem no handler: %s", e)
