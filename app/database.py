from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


class ConversationState(str, Enum):
    AWAITING_TOPIC = "awaiting_topic"
    AWAITING_ANSWER = "awaiting_answer"
    AWAITING_CONTINUE = "awaiting_continue"
    AWAITING_REDO = "awaiting_redo"


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped["StudentSession | None"] = relationship(back_populates="contact")
    progress: Mapped[list["StudentProgress"]] = relationship(back_populates="contact")


class StudentSession(Base):
    __tablename__ = "student_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), unique=True)
    state: Mapped[str] = mapped_column(String(40), default=ConversationState.AWAITING_TOPIC.value)
    current_topic: Mapped[str | None] = mapped_column(String(120), nullable=True)
    current_question_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_question_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    contact: Mapped["Contact"] = relationship(back_populates="session")


class StudentProgress(Base):
    __tablename__ = "student_progress"
    __table_args__ = (UniqueConstraint("contact_id", "question_id", name="uq_contact_question"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    topic: Mapped[str] = mapped_column(String(120), index=True)
    question_id: Mapped[str] = mapped_column(String(255), index=True)
    question_name: Mapped[str] = mapped_column(String(255))
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_correct: Mapped[str | None] = mapped_column(String(20), nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    contact: Mapped["Contact"] = relationship(back_populates="progress")


class MediaCache(Base):
    __tablename__ = "media_cache"

    drive_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    whatsapp_id: Mapped[str] = mapped_column(String(255), nullable=False)


# Nova tabela para o sistema de Resolução de Elite
class QuestionResolution(Base):
    __tablename__ = "question_resolutions"
    
    question_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    gabarito: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolucao_latex: Mapped[str | None] = mapped_column(Text, nullable=True)
    imagem_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    from pathlib import Path

    if settings.database_url.startswith("sqlite"):
        db_path = settings.database_url.replace("sqlite:///", "")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
