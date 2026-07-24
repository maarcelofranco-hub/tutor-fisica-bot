import logging
import mimetypes
import unicodedata
from pathlib import Path

from app.config import settings
from app.models.schemas import Question
from app.services.drive import DriveFile, DriveService
from app.utils.text import labels_match, normalize_label

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


class LocalQuestionProvider:
    def __init__(self, root_path: Path) -> None:
        self.root_path = root_path
        self.root_path.mkdir(parents=True, exist_ok=True)
        self.themes_folder_name = settings.drive_themes_folder_name

    def list_topics(self) -> list[str]:
        reserved = normalize_label(self.themes_folder_name)
        return sorted(
            folder.name
            for folder in self.root_path.iterdir()
            if folder.is_dir()
            and not folder.name.startswith(".")
            and normalize_label(folder.name) != reserved
        )

    def list_questions(self, topic: str) -> list[Question]:
        topic_path = self._find_topic_path(topic)
        if not topic_path:
            return []

        questions: list[Question] = []
        for file_path in sorted(topic_path.iterdir()):
            if file_path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            mime_type = mimetypes.guess_type(file_path.name)[0] or "image/png"
            questions.append(
                Question(
                    id=str(file_path.resolve()),
                    name=file_path.name,
                    topic=topic_path.name,
                    mime_type=mime_type,
                )
            )
        return questions

    def get_question_image(self, question_id: str) -> tuple[bytes, str]:
        path = Path(question_id)
        if not path.exists():
            raise FileNotFoundError(f"Question not found: {question_id}")
        mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
        return path.read_bytes(), mime_type

    def get_themes_menu_file(self) -> DriveFile | None:
        themes_path = None
        for folder in self.root_path.iterdir():
            if folder.is_dir() and labels_match(folder.name, self.themes_folder_name):
                themes_path = folder
                break
        if not themes_path:
            return None
        for file_path in sorted(themes_path.iterdir()):
            suffix = file_path.suffix.lower()
            if suffix == ".pdf":
                return DriveFile(
                    id=str(file_path.resolve()),
                    name=file_path.name,
                    mime_type="application/pdf",
                )
            if suffix in IMAGE_EXTENSIONS:
                mime_type = mimetypes.guess_type(file_path.name)[0] or "image/jpeg"
                return DriveFile(id=str(file_path.resolve()), name=file_path.name, mime_type=mime_type)
        return None

    def download_file(self, file_id: str) -> tuple[bytes, str]:
        path = Path(file_id)
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return path.read_bytes(), mime_type

    def topic_exists(self, topic: str) -> bool:
        return self._find_topic_path(topic) is not None

    def refresh_cache(self) -> None:
        return None

    def _find_topic_path(self, topic: str) -> Path | None:
        for folder_name in self.list_topics() + [self.themes_folder_name]:
            if labels_match(folder_name, topic):
                return self.root_path / folder_name
        return None


class QuestionProvider:
    def __init__(self) -> None:
        self.local = LocalQuestionProvider(Path(settings.local_questions_path))
        self.drive = DriveService()
        self.mode = self._resolve_mode()
        logger.info("Question provider mode: %s", self.mode)

    def _resolve_mode(self) -> str:
        source = settings.question_source.lower()
        if source == "local":
            return "local"
        if source == "drive":
            if not self.drive.is_configured:
                logger.warning("QUESTION_SOURCE=drive but Drive is not configured; falling back to local")
                return "local"
            return "drive"
        if self.drive.is_configured:
            return "drive"
        return "local"

    def _provider(self):
        return self.drive if self.mode == "drive" else self.local

    async def refresh(self) -> None:
        # 1. Atualiza apenas o cache do Drive (Baixa novas fotos que você colocar na pasta)
        if self.mode == "drive":
            self.drive.refresh_cache()
        # GEMINI REMOVIDO DAQUI DEFINITIVAMENTE PARA NÃO GASTAR TOKENS

    def list_topics(self) -> list[str]:
        return self._provider().list_topics()

    def list_questions(self, topic: str) -> list[Question]:
        # 2. FILTRO: Remove as resoluções da lista de perguntas!
        all_files = self._provider().list_questions(topic)
        questions = []
        
        for f in all_files:
            name_normalized = ''.join(c for c in unicodedata.normalize('NFD', f.name) if unicodedata.category(c) != 'Mn').lower()
            # Só adiciona na lista de exercícios se NÃO tiver "resolucao" no nome
            if "resolucao" not in name_normalized:
                questions.append(f)
                
        return questions

    def get_question_image(self, question_id: str) -> tuple[bytes, str]:
        return self._provider().get_question_image(question_id)

    def get_themes_menu_file(self):
        return self._provider().get_themes_menu_file()

    def download_file(self, file_id: str) -> tuple[bytes, str]:
        if self.mode == "drive":
            return self.drive.download_file(file_id)
        return self.local.download_file(file_id)

    def topic_exists(self, topic: str) -> bool:
        return self._provider().topic_exists(topic)

    def resolve_topic_name(self, topic: str) -> str:
        for name in self.list_topics():
            if labels_match(name, topic):
                return name
        return topic.strip()

question_provider = QuestionProvider()
