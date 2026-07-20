import io
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from google.oauth2 import service_account
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from app.config import settings
from app.models.schemas import Question
from app.utils.text import labels_match, normalize_label

logger = logging.getLogger(__name__)

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

@dataclass
class DriveFile:
    id: str
    name: str
    mime_type: str

class DriveService:
    IMAGE_MIME_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
    PDF_MIME = "application/pdf"

    def __init__(self) -> None:
        self.root_folder_id = settings.google_drive_root_folder_id
        self.themes_folder_name = settings.drive_themes_folder_name
        self.service = self._build_service()
        self._folder_cache: dict[str, str] = {}
        self._topics_cache: list[str] | None = None
        self._questions_cache: dict[str, list[Question]] = {}
        self._menu_file_cache: DriveFile | None = None

    def refresh_cache(self) -> None:
        """Limpa o cache de temas e força a recarga."""
        self._topics_cache = None
        self._questions_cache = {}
        self.list_topics()

    @property
    def is_configured(self) -> bool:
        return self.service is not None and bool(self.root_folder_id)

    def _build_service(self):
        credentials = self._load_service_account_credentials()
        if not credentials:
            logger.error("Falha ao carregar credenciais da Service Account.")
            return None
        return build("drive", "v3", credentials=credentials, cache_discovery=False)

    def _load_service_account_credentials(self):
        # Caminho fixo onde o arquivo está mapeado no container
        file_path = "/app/credentials/service-account.json"
        
        if os.path.exists(file_path):
            try:
                logger.info(f"Carregando credenciais do arquivo: {file_path}")
                return service_account.Credentials.from_service_account_file(file_path, scopes=DRIVE_SCOPES)
            except Exception as e:
                logger.error("Erro ao carregar arquivo de credenciais: %s", e)
        else:
            logger.error(f"Arquivo de credenciais não encontrado em: {file_path}")
        return None

    def list_topics(self) -> list[str]:
        if not self.is_configured:
            logger.warning("Drive não configurado!")
            return []
            
        logger.info(f"DEBUG: Listando pastas a partir do ID raiz: {self.root_folder_id}")
        folders = self._list_child_folders(self.root_folder_id)
        
        folder_names = [f.name for f in folders]
        logger.info(f"DEBUG: Pastas encontradas no Drive: {folder_names}")
        
        reserved = normalize_label(self.themes_folder_name)
        
        self._topics_cache = sorted(
            folder.name
            for folder in folders
            if normalize_label(folder.name) != reserved
        )
        logger.info(f"DEBUG: Temas finais detectados: {self._topics_cache}")
        return self._topics_cache

    def list_questions(self, topic: str) -> list[Question]:
        if not self.is_configured: return []
        normalized_topic = normalize_label(topic)
        if normalized_topic in self._questions_cache: return self._questions_cache[normalized_topic]
        
        topic_folder_id = self._find_topic_folder_id(topic)
        logger.info(f"DEBUG: Buscando questões para o tema '{topic}'. ID da pasta encontrado: {topic_folder_id}")
        
        if not topic_folder_id: return []

        response = self.service.files().list(
            q=f"'{topic_folder_id}' in parents and trashed=false and mimeType contains 'image/'",
            fields="files(id, name, mimeType, webContentLink)",
            orderBy="name", pageSize=200, supportsAllDrives=True, includeItemsFromAllDrives=True
        ).execute()

        questions = [Question(id=item["id"], name=item["name"], topic=topic, image_url=item.get("webContentLink"), mime_type=item.get("mimeType", "image/jpeg")) 
                     for item in response.get("files", []) if item.get("mimeType") in self.IMAGE_MIME_TYPES]
        
        self._questions_cache[normalized_topic] = questions
        return questions

    def _list_child_folders(self, parent_id: str) -> list[DriveFile]:
        try:
            response = self.service.files().list(
                q=f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
                fields="files(id, name, mimeType)", supportsAllDrives=True, includeItemsFromAllDrives=True
            ).execute()
            return [DriveFile(id=item["id"], name=item["name"], mime_type="") for item in response.get("files", [])]
        except Exception as e:
            logger.error(f"DEBUG: Erro ao listar pastas filhas: {e}")
            return []

    def _find_folder_by_name(self, parent_id: str, folder_name: str) -> str | None:
        folders = self._list_child_folders(parent_id)
        for folder in folders:
            if labels_match(folder.name, folder_name): return folder.id
        return None

    def _find_topic_folder_id(self, topic: str) -> str | None:
        return self._find_folder_by_name(self.root_folder_id, topic)
