# ... (mantenha os imports e o início da classe iguais)

class DriveService:
    # ... (mantenha as constantes e o __init__ existentes)

    def warm_up_cache(self) -> None:
        """Varre todas as pastas e coloca as imagens no cache local."""
        logger.info("Iniciando pré-carregamento do cache (warm-up)...")
        try:
            topics = self.list_topics()
            for topic in topics:
                questions = self.list_questions(topic)
                for q in questions:
                    # Ao chamar o get_question_image, o seu _download_file 
                    # já verifica se existe no cache. Se não existir, baixa.
                    self.get_question_image(q.id)
            logger.info("Cache pré-carregado com sucesso!")
        except Exception as e:
            logger.error("Erro ao pré-carregar cache: %s", e)

    # ... (mantenha o restante das funções _download_file, etc.)
