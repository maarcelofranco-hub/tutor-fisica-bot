import io

from PIL import Image

from app.services.gemini import GeminiService


class OCRService:
    def __init__(self, gemini_service: GeminiService) -> None:
        self.gemini = gemini_service

    async def extract_text(self, image_bytes: bytes, mime_type: str = "image/png") -> str:
        prepared = self._prepare_image(image_bytes)
        return await self.gemini.extract_text_from_image(prepared, mime_type)

    def _prepare_image(self, image_bytes: bytes) -> bytes:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=90)
        return output.getvalue()
