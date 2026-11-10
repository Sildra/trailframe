from __future__ import annotations

from io import BytesIO
from pathlib import Path

import allure
from PIL import Image

from trailframe.services.photos.processing_service import ProcessingService


class Upload:
    """Minimal stand-in for FastAPI's UploadFile: only async `read` is used."""

    def __init__(self, content: bytes):
        self._buffer = BytesIO(content)

    async def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)


def _image() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (32, 24), (10, 120, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


def _folders(tmp_path) -> tuple[Path, Path]:
    return tmp_path / "data" / "processed", tmp_path / "data" / "originals"


class TestProcessingService:
    @allure.title("Stores an upload as an original and generates the configured alternative")
    def test_upload_stores_original_and_alternative(self, app, tmp_path):
        processed, originals = _folders(tmp_path)

        photo = app.db(ProcessingService.upload("shot.png", Upload(_image())))

        assert (originals / "shot.png").is_file()
        assert photo.path == "shot.png"
        assert photo.filename == "shot.png"
        assert len(photo.alternatives) == 1

        entry = photo.alternatives[0]
        assert entry["target_size"] == 1080
        assert entry["main"] is True
        assert (processed / entry["path"]).is_file()
        assert photo.main().path == entry["path"]
        assert photo.main().target_size == 1080
        assert [step["format"] for step in photo.processing] == ["webp"]

    @allure.title("Keeps earlier originals and gives a repeated upload a unique name")
    def test_upload_keeps_existing_originals(self, app, tmp_path):
        processed, originals = _folders(tmp_path)

        first = app.db(ProcessingService.upload("shot.png", Upload(_image())))
        second = app.db(ProcessingService.upload("shot.png", Upload(_image())))

        assert first.path == "shot.png"
        assert second.path == "shot_1.png"
        assert len(list(originals.glob("shot*.png"))) == 2
        assert len(list(processed.glob("shot*.webp"))) == 2

    @allure.title("Imports an original left behind in the originals folder")
    def test_scan_processes_leftover_originals(self, app, tmp_path):
        processed, originals = _folders(tmp_path)
        originals.mkdir(parents=True, exist_ok=True)
        (originals / "left.png").write_bytes(_image())

        app.db(ProcessingService.scan())

        assert (originals / "left.png").is_file()
        assert len(list(processed.glob("left*.webp"))) == 1

    @allure.title("Does not import an original that was already processed")
    def test_scan_skips_already_processed_originals(self, app, tmp_path):
        processed, _ = _folders(tmp_path)

        app.db(ProcessingService.upload("shot.png", Upload(_image())))
        app.db(ProcessingService.scan())

        assert len(list(processed.glob("shot*.webp"))) == 1

    @allure.title("Falls back to the original when a photo has no alternatives")
    def test_legacy_photo_main_is_original(self):
        from trailframe.models.photo import Photo

        photo = Photo(path="legacy.jpg", filename="legacy.jpg")

        assert photo.main().is_original is True
        assert photo.main().path == "legacy.jpg"
        assert photo.alternative(1080) is None
