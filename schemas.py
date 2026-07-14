from pydantic import BaseModel, Field


class Question(BaseModel):
    id: str
    name: str
    topic: str
    image_url: str | None = None
    mime_type: str = "image/png"


class CorrectionResult(BaseModel):
    is_correct: bool
    feedback: str
    explanation: str | None = None


class IncomingMessage(BaseModel):
    phone: str
    message_id: str = ""
    text: str | None = None
    media_id: str | None = None
    media_mime_type: str | None = None
    image_bytes: bytes | None = None
    contact_name: str | None = None


class TestMessageRequest(BaseModel):
    phone: str = "5511999999999"
    text: str | None = None
    contact_name: str | None = "Aluno Teste"


class OutboundMessageResponse(BaseModel):
    type: str
    content: str
    image_name: str | None = None


class SessionResponse(BaseModel):
    phone: str
    state: str
    current_topic: str | None = None
    current_question_name: str | None = None
    answered_count: int = 0


class TopicsResponse(BaseModel):
    topics: list[str] = Field(default_factory=list)
