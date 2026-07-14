from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    database_url: str = "sqlite:///./data/app.db"

    question_source: str = "auto"
    local_questions_path: str = "./data/questions"

    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = "change-me"
    whatsapp_api_version: str = "v21.0"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_correction_style: str = "detailed"

    google_drive_root_folder_id: str = ""
    google_service_account_file: str = "./credentials/google-service-account.json"
    google_service_account_json: str = ""
    google_oauth_client_file: str = "./credentials/google-oauth-client.json"
    google_oauth_token_file: str = "./credentials/google-oauth-token.json"
    drive_themes_folder_name: str = "Temas"
    drive_sync_on_startup: bool = False

    welcome_message: str = "Qual tema voce quer estudar? Envie o nome exatamente como no PDF."
    continue_question_message: str = "Voce deseja receber outra questao deste tema?"
    redo_topic_message: str = (
        "Parabens! Voce concluiu todas as questoes deste tema. "
        "Deseja refazer este tema desde o inicio? Responda sim ou nao."
    )
    topic_completed_message: str = (
        "Escolha outro tema para continuar seus estudos."
    )


settings = Settings()
