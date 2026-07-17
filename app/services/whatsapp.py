import httpx
from app.config import settings

class WhatsAppService:
    def __init__(self) -> None:
        self.base_url = (
            f"https://graph.facebook.com/{settings.whatsapp_api_version}/"
            f"{settings.whatsapp_phone_number_id}"
        )
        self.headers = {
            "Authorization": f"Bearer {settings.whatsapp_access_token}",
            "Content-Type": "application/json",
        }

    @property
    def is_configured(self) -> bool:
        return bool(settings.whatsapp_access_token and settings.whatsapp_phone_number_id)

    async def send_text(self, phone: str, text: str) -> None:
        from app.utils.phone import normalize_phone
        phone = normalize_phone(phone)
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "text",
            "text": {"body": text},
        }
        await self._post("/messages", payload)

    async def send_image_url(self, phone: str, image_url: str, caption: str | None = None) -> None:
        image_payload: dict = {"link": image_url}
        if caption:
            image_payload["caption"] = caption
        await self._post(
            "/messages",
            {
                "messaging_product": "whatsapp",
                "to": phone,
                "type": "image",
                "image": image_payload,
            },
        )

    # Nova função para envio instantâneo via media_id
    async def send_image_by_id(self, phone: str, media_id: str, caption: str | None = None) -> None:
        from app.utils.phone import normalize_phone
        phone = normalize_phone(phone)
        image_payload: dict = {"id": media_id}
        if caption:
            image_payload["caption"] = caption
            
        await self._post(
            "/messages",
            {
                "messaging_product": "whatsapp",
                "to": phone,
                "type": "image",
                "image": image_payload,
            },
        )

    async def send_image_bytes(
        self,
        phone: str,
        image_bytes: bytes,
        mime_type: str,
        caption: str | None = None,
    ) -> None:
        from app.utils.phone import normalize_phone
        phone = normalize_phone(phone)
        media_id = await self._upload_media(image_bytes, mime_type)
        image_payload: dict = {"id": media_id}
        if caption:
            image_payload["caption"] = caption
        await self._post(
            "/messages",
            {
                "messaging_product": "whatsapp",
                "to": phone,
                "type": "image",
                "image": image_payload,
            },
        )

    async def send_document_bytes(
        self,
        phone: str,
        file_bytes: bytes,
        mime_type: str,
        filename: str,
        caption: str | None = None,
    ) -> None:
        from app.utils.phone import normalize_phone
        phone = normalize_phone(phone)
        media_id = await self._upload_media(file_bytes, mime_type, filename=filename)
        document_payload: dict = {"id": media_id, "filename": filename}
        if caption:
            document_payload["caption"] = caption
        await self._post(
            "/messages",
            {
                "messaging_product": "whatsapp",
                "to": phone,
                "type": "document",
                "document": document_payload,
            },
        )

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            meta_response = await client.get(
                f"https://graph.facebook.com/{settings.whatsapp_api_version}/{media_id}",
                headers=self.headers,
            )
            meta_response.raise_for_status()
            media_url = meta_response.json()["url"]

            file_response = await client.get(media_url, headers=self.headers)
            file_response.raise_for_status()
            mime_type = file_response.headers.get("content-type", "application/octet-stream")
            return file_response.content, mime_type

    async def _upload_media(self, file_bytes: bytes, mime_type: str, filename: str = "question.png") -> str:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/media",
                headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
                data={"messaging_product": "whatsapp", "type": mime_type},
                files={"file": (filename, file_bytes, mime_type)},
            )
            response.raise_for_status()
            return response.json()["id"]

    async def _post(self, path: str, payload: dict) -> None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{self.base_url}{path}", headers=self.headers, json=payload)
            response.raise_for_status()
