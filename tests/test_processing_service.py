from __future__ import annotations

import math
from io import BytesIO
from pathlib import Path

import allure
import pytest
from PIL import Image, ImageDraw

from trailframe.services.photos.processing.tilt import TiltSettings
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


def _tilted_image(angle: float = 2.0, size: tuple[int, int] = (900, 600)) -> bytes:
    image = Image.new("RGB", size, (245, 245, 245))
    draw = ImageDraw.Draw(image)
    left, right = 30, size[0] - 30
    width = right - left
    center = size[1] / 2
    draw.line((left, center, right, center - width * math.tan(math.radians(angle))), fill=(10, 10, 10), width=4)
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    return buffer.getvalue()


def _folders(tmp_path) -> tuple[Path, Path]:
    return tmp_path / "data" / "processed", tmp_path / "data" / "photos"


class TestProcessingService:
    @allure.title("Stores an upload as an original and generates the configured alternative")
    def test_upload_stores_original_and_alternative(self, app, tmp_path):
        processed, photos = _folders(tmp_path)

        photo = app.db(ProcessingService.upload("shot.png", Upload(_image())))

        assert (photos / "shot.png").is_file()
        assert photo.path == "shot.png"
        assert photo.filename == "shot.png"
        assert len(photo.alternatives) == 1

        entry = photo.alternatives[0]
        assert entry["target_size"] == 1080
        assert entry["main"] is True
        assert (processed / entry["path"]).is_file()
        assert photo.main().path == entry["path"]
        assert photo.main().target_size == 1080

        output = next(step for step in photo.processing if step["step"] in {"downscale", "transcode"})
        assert output["summary"] == f"{entry['width']} × {entry['height']}"
        assert output["details"] == {
            "Target size": "1080 px",
            "Format": "WEBP",
            "Quality": "90",
        }
        assert output["meta"] == {}

    @allure.title("Straightens a tilted horizon, records it and keeps the original untouched")
    def test_upload_corrects_tilt(self, app, tmp_path):
        processed, photos = _folders(tmp_path)

        photo = app.db(ProcessingService.upload("tilted.png", Upload(_tilted_image())))
        entry = photo.alternatives[0]

        assert entry["width"] < 900
        assert entry["height"] < 600
        assert (processed / entry["path"]).is_file()

        tilt = next(step for step in photo.processing if step["step"] == "tilt")
        details = tilt["details"]
        meta = tilt["meta"]
        assert details["Detection method"] == "hough"
        assert details["Applied"] == "Yes"
        assert details["Confidence"].endswith("%")
        assert "Reference point" in details
        assert "Reason" not in details
        assert tilt["summary"].endswith("°")
        assert float(tilt["summary"].rstrip("°")) == pytest.approx(-2.0, abs=0.5)
        assert 0 <= meta["reference_point"]["x"] <= 1
        assert 0 <= meta["reference_point"]["y"] <= 1
        assert meta["line"]["x1"] < meta["line"]["x2"]

        transcode = next(step for step in photo.processing if step["step"] == "transcode")
        assert transcode["details"]["Target size"] == "1080 px"

        with Image.open(photos / "tilted.png") as original:
            assert original.size == (900, 600)

    @allure.title("Tilt correction can be disabled")
    def test_tilt_disabled(self, app, tmp_path):
        previous = ProcessingService._tilt
        ProcessingService._tilt = TiltSettings(enabled=False)

        try:
            photo = app.db(ProcessingService.upload("flat.png", Upload(_tilted_image())))
        finally:
            ProcessingService._tilt = previous

        assert photo.alternatives[0]["width"] == 900
        assert all(step["step"] != "tilt" for step in photo.processing)

    @allure.title("Keeps earlier originals and gives a repeated upload a unique name")
    def test_upload_keeps_existing_originals(self, app, tmp_path):
        processed, photos = _folders(tmp_path)

        first = app.db(ProcessingService.upload("shot.png", Upload(_image())))
        second = app.db(ProcessingService.upload("shot.png", Upload(_image())))

        assert first.path == "shot.png"
        assert second.path == "shot_1.png"
        assert len(list(photos.glob("shot*.png"))) == 2
        assert len(list(processed.glob("shot*.webp"))) == 2

    @allure.title("Imports an original left behind in the photos folder")
    def test_scan_processes_leftover_originals(self, app, tmp_path):
        processed, photos = _folders(tmp_path)
        photos.mkdir(parents=True, exist_ok=True)
        (photos / "left.png").write_bytes(_image())

        app.db(ProcessingService.scan())

        assert (photos / "left.png").is_file()
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
