import io
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
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
        
        # 🚀 CACHES EM MEMÓRIA ADICIONADOS AQUI
        self._folder_cache: dict[str, str] = {}
        self._topics_cache: list[str] | None = None
        self._questions_cache: dict[str, list[Question]] = {}
        self._menu_file_cache: DriveFile | None = None

    @property
    def is_configured(self) -> bool:
        return self.service is not None and bool(self.root_folder_id)

    def warm_up_cache(self) -> None:
        """Varre todas as pastas e coloca as imagens no cache local."""
        logger.info("Iniciando pré-carregamento do cache (warm-up)...")
        try:
            topics = self.list_topics()
            for topic in topics:
                questions = self.list_questions(topic)
                for q in questions:
                    self.get_question_image(q.id)
            logger.info("Cache pré-carregado com sucesso!")
        except Exception as e:
            logger.error("Erro ao pré-carregar cache: %s", e)

    def _build_service(self):
        credentials = self._load_service_account_credentials()
        if credentials is None:
            credentials = self._load_oauth_credentials()
        if credentials is None:
            return None
        return build("drive", "v3", credentials=credentials, cache_discovery=False)

    def _load_service_account_credentials(self):
        if settings.google_service_account_json.strip():
            try:
                info = json.loads(settings.google_service_account_json)
                return service_account.Credentials.from_service_account_info(info, scopes=DRIVE_SCOPES)
            except json.JSONDecodeError:
                logger.error("GOOGLE_SERVICE_ACCOUNT_JSON is invalid JSON")
                return None

        credentials_path = Path(settings.google_service_account_file)
        if credentials_path.exists():
            return service_account.Credentials.from_service_account_file(
                str(credentials_path),
                scopes=DRIVE_SCOPES,
            )
        return None

    def _load_oauth_credentials(self):
        token_path = Path(settings.google_oauth_token_file)
        if not token_path.exists():
            logger.warning("Google OAuth token not found: %s", token_path)
            return None
        credentials = Credentials.from_authorized_user_file(str(token_path), DRIVE_SCOPES)
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            token_path.write_text(credentials.to_json(), encoding="utf-8")
        if not credentials.valid:
            logger.warning("Google OAuth token is invalid. Run authorize_google_drive.py")
            return None
        return credentials

    def refresh_cache(self) -> None:
        """Limpa todos os caches em memória para permitir atualização controlada."""
        self._folder_cache.clear()
        self._topics_cache = None
        self._questions_cache.clear()
        self._menu_file_cache = None
        logger.info("Cache do DriveService completamente limpo.")

    def list_topics(self) -> list[str]:
        if not self.is_configured:
            return []
            
        # Retorna o cache se já foi listado anteriormente
        if self._topics_cache is not None:
            return self._topics_cache

        folders = self._list_child_folders(self.root_folder_id)
        reserved = normalize_label(self.themes_folder_name)
        
        self._topics_cache = sorted(
            folder.name
            for folder in folders
            if normalize_label(folder.name) != reserved
        )
        return self._topics_cache

    def list_questions(self, topic: str) -> list[Question]:
        if not self.is_configured:
            return []
        
        # Procura a lista diretamente no cache em memória
        normalized_topic = normalize_label(topic)
        if normalized_topic in self._questions_cache:
            return self._questions_cache[normalized_topic]

        topic_folder_id = self._find_topic_folder_id(topic)
        if not topic_folder_id:
            return []

        response = (
            self.service.files()
            .list(
                q=(
                    f"'{topic_folder_id}' in parents and trashed=false and "
                    "mimeType contains 'image/'"
                ),
                fields="files(id, name, mimeType, webContentLink)",
                orderBy="name",
                pageSize=200,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )

        questions: list[Question] = []
        for item in response.get("files", []):
            if item.get("mimeType") not in self.IMAGE_MIME_TYPES:
                continue
            questions.append(
                Question(
                    id=item["id"],
                    name=item["name"],
                    topic=self._resolve_topic_name(topic),
                    image_url=item.get("webContentLink"),
                    mime_type=item.get("mimeType", "image/jpeg"),
                )
            )
            
        # Salva o resultado no cache antes de retornar
        self._questions_cache[normalized_topic] = questions
        return questions

    def get_question_image(self, question_id: str) -> tuple[bytes, str]:
        if not self.service:
            raise RuntimeError("Google Drive is not configured.")
        return self._download_file(question_id)

    def get_themes_menu_file(self) -> DriveFile | None:
        if not self.is_configured:
            return None
            
        # Retorna o cache do menu se já existir
        if self._menu_file_cache is not None:
            return self._menu_file_cache

        themes_folder_id = self._find_folder_by_name(self.root_folder_id, self.themes_folder_name)
        if not themes_folder_id:
            logger.warning("Themes folder '%s' not found on Drive", self.themes_folder_name)
            return None

        response = (
            self.service.files()
            .list(
                q=f"'{themes_folder_id}' in parents and trashed=false",
                fields="files(id, name, mimeType)",
                orderBy="name",
                pageSize=50,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files = response.get("files", [])
        menu_file = None
        for item in files:
            if item.get("mimeType") == self.PDF_MIME:
                menu_file = DriveFile(id=item["id"], name=item["name"], mime_type=self.PDF_MIME)
                break
        if not menu_file:
            for item in files:
                mime = item.get("mimeType", "")
                if mime.startswith("image/"):
                    menu_file = DriveFile(id=item["id"], name=item["name"], mime_type=mime)
                    break
                    
        self._menu_file_cache = menu_file
        return menu_file

    def download_file(self, file_id: str) -> tuple[bytes, str]:
        return self._download_file(file_id)

    def topic_exists(self, topic: str) -> bool:
        return self._find_topic_folder_id(topic) is not None

    def _download_file(self, file_id: str) -> tuple[bytes, str]:
        cache_dir = Path("cache")
        cache_dir.mkdir(exist_ok=True)
        file_path = cache_dir / f"{file_id}.bin"
        meta_path = cache_dir / f"{file_id}.meta"

        if file_path.exists() and meta_path.exists():
            with open(file_path, "rb") as f:
                data = f.read()
            mime_type = meta_path.read_text()
            return data, mime_type

        metadata = self.service.files().get(
            fileId=file_id,
            fields="mimeType,name",
            supportsAllDrives=True,
        ).execute()
        request = self.service.files().get_media(fileId=file_id, supportsAllDrives=True)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        
        data = buffer.getvalue()
        mime_type = metadata.get("mimeType", "application/octet-stream")

        with open(file_path, "wb") as f:
            f.write(data)
        meta_path.write_text(mime_type)

        return data, mime_type

    def _list_child_folders(self, parent_id: str) -> list[DriveFile]:
        response = (
            self.service.files()
            .list(
                q=(
                    f"'{parent_id}' in parents and "
                    "mimeType='application/vnd.google-apps.folder' and trashed=false"
                ),
                fields="files(id, name, mimeType)",
                orderBy="name",
                pageSize=200,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        return [
            DriveFile(id=item["id"], name=item["name"], mime_type=item.get("mimeType", ""))
            for item in response.get("files", [])
        ]

    def _find_topic_folder_id(self, topic: str) -> str | None:
        return self._find_folder_by_name(self.root_folder_id, topic, exclude_themes=True)

    def _find_folder_by_name(
        self,
        parent_id: str,
        folder_name: str,
        exclude_themes: bool = False,
    ) -> str | None:
        cache_key = f"{parent_id}:{folder_name}:{exclude_themes}"
        if cache_key in self._folder_cache:
            return self._folder_cache[cache_key]

        for folder in self._list_child_folders(parent_id):
            if exclude_themes and labels_match(folder.name, self.themes_folder_name):
                continue
            if labels_match(folder.name, folder_name):
                self._folder_cache[cache_key] = folder.id
                return folder.id
        return None

    def _resolve_topic_name(self, topic: str) -> str:
        for name in self.list_topics():
            if labels_match(name, topic):
                return name
        return topic.strip()
