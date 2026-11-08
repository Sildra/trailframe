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
    return tmp_path / "data" / "photos", tmp_path / "data" / "originals"


class TestProcessingService:
    @allure.title("Stages an upload in the originals folder and copies it into the photos folder")
    def test_upload_stages_then_copies(self, app, tmp_path):
        photos, originals = _folders(tmp_path)

        path = app.db(ProcessingService.upload("shot.png", Upload(_image())))

        assert (originals / "shot.png").is_file()
        assert path == photos / "shot.png"
        assert path.is_file()

    @allure.title("Keeps earlier originals and gives a repeated upload a unique name")
    def test_upload_keeps_existing_originals(self, app, tmp_path):
        photos, originals = _folders(tmp_path)

        first = app.db(ProcessingService.upload("shot.png", Upload(_image())))
        second = app.db(ProcessingService.upload("shot.png", Upload(_image())))

        assert first.name == "shot.png"
        assert second.name == "shot_1.png"
        assert len(list(originals.glob("shot*.png"))) == 2
        assert len(list(photos.glob("shot*.png"))) == 2

    @allure.title("Imports an original left behind in the originals folder")
    def test_scan_processes_leftover_originals(self, app, tmp_path):
        photos, originals = _folders(tmp_path)
        originals.mkdir(parents=True, exist_ok=True)
        (originals / "left.png").write_bytes(_image())

        app.db(ProcessingService.scan())

        assert (photos / "left.png").is_file()
        assert (originals / "left.png").is_file()

    @allure.title("Does not import an original that was already copied")
    def test_scan_skips_already_copied_originals(self, app, tmp_path):
        photos, _ = _folders(tmp_path)

        app.db(ProcessingService.upload("shot.png", Upload(_image())))
        app.db(ProcessingService.scan())

        assert len(list(photos.glob("shot*.png"))) == 1
