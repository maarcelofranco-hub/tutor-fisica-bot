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

    @property
    def is_configured(self) -> bool:
        return self.service is not None and bool(self.root_folder_id)

    def _build_service(self):
        """Constrói o serviço focando na Service Account configurada no .env"""
        credentials = self._load_service_account_credentials()
        if not credentials:
            logger.error("Falha ao carregar credenciais da Service Account. Verifique seu .env!")
            return None
        return build("drive", "v3", credentials=credentials, cache_discovery=False)

    def _load_service_account_credentials(self):
        # Tenta carregar do JSON salvo na variável de ambiente .env
        if settings.google_service_account_json and settings.google_service_account_json.strip():
            try:
                info = json.loads(settings.google_service_account_json)
                return service_account.Credentials.from_service_account_info(info, scopes=DRIVE_SCOPES)
            except Exception as e:
                logger.error("Erro ao processar JSON da Service Account: %s", e)
        return None

    # Métodos restantes inalterados para manter sua lógica de cache...
    def list_topics(self) -> list[str]:
        if not self.is_configured: return []
        if self._topics_cache is not None: return self._topics_cache
        folders = self._list_child_folders(self.root_folder_id)
        reserved = normalize_label(self.themes_folder_name)
        self._topics_cache = sorted(folder.name for folder in folders if normalize_label(folder.name) != reserved)
        return self._topics_cache

    def list_questions(self, topic: str) -> list[Question]:
        if not self.is_configured: return []
        normalized_topic = normalize_label(topic)
        if normalized_topic in self._questions_cache: return self._questions_cache[normalized_topic]
        topic_folder_id = self._find_topic_folder_id(topic)
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

    def _download_file(self, file_id: str) -> tuple[bytes, str]:
        metadata = self.service.files().get(fileId=file_id, fields="mimeType", supportsAllDrives=True).execute()
        request = self.service.files().get_media(fileId=file_id, supportsAllDrives=True)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        return buffer.getvalue(), metadata.get("mimeType", "application/octet-stream")

    def _list_child_folders(self, parent_id: str) -> list[DriveFile]:
        response = self.service.files().list(
            q=f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
            fields="files(id, name, mimeType)", supportsAllDrives=True, includeItemsFromAllDrives=True
        ).execute()
        return [DriveFile(id=item["id"], name=item["name"], mime_type="") for item in response.get("files", [])]

    def _find_folder_by_name(self, parent_id: str, folder_name: str, exclude_themes: bool = False) -> str | None:
        for folder in self._list_child_folders(parent_id):
            if labels_match(folder.name, folder_name): return folder.id
        return None

    def _find_topic_folder_id(self, topic: str) -> str | None:
        return self._find_folder_by_name(self.root_folder_id, topic)
