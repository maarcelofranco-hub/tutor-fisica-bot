from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class OutboundMessage:
    phone: str
    type: str
    content: str
    image_name: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)


class OutboxStore:
    def __init__(self) -> None:
        self._messages: dict[str, list[OutboundMessage]] = {}

    def add_text(self, phone: str, text: str) -> None:
        self._add(phone, OutboundMessage(phone=phone, type="text", content=text))

    def add_image(self, phone: str, image_name: str, caption: str | None = None) -> None:
        self._add(
            phone,
            OutboundMessage(
                phone=phone,
                type="image",
                content=caption or image_name,
                image_name=image_name,
            ),
        )

    def get_messages(self, phone: str, clear: bool = False) -> list[OutboundMessage]:
        messages = list(self._messages.get(phone, []))
        if clear:
            self._messages[phone] = []
        return messages

    def clear(self, phone: str) -> None:
        self._messages[phone] = []

    def _add(self, phone: str, message: OutboundMessage) -> None:
        self._messages.setdefault(phone, []).append(message)


outbox = OutboxStore()
