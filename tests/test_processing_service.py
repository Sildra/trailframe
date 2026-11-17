from __future__ import annotations

import math
import time
from io import BytesIO
from pathlib import Path

import allure
import pytest
from PIL import Image, ImageDraw
from sqlalchemy import select

from trailframe.models.photo import Photo
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.photos.folder_service import FolderService
from trailframe.services.photos.processing.tilt import TiltOverride, TiltSettings
from trailframe.services.photos.processing_service import ProcessingService, ReprocessError
from trailframe.services.photos.thumbnail_service import ThumbnailService


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


def _wide_image(size: tuple[int, int] = (1200, 800)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, (30, 90, 150)).save(buffer, format="PNG")
    return buffer.getvalue()


def _seed_photo(app, tmp_path, *, filename: str | None = None, source: str = "File") -> Photo:
    """Store an original plus its alternatives directly, without the pipeline.

    The default name is unique per test: a pipeline thread from an earlier app
    can outlive its shutdown (stop joins with a timeout) and write its own
    photos into the next app's database.
    """
    _, photos = _folders(tmp_path)
    photos.mkdir(parents=True, exist_ok=True)
    filename = filename or f"seed-{tmp_path.name}.png"
    original = photos / filename
    original.write_bytes(_wide_image())

    photo = Photo(path=filename, filename=filename, file_size=original.stat().st_size, source=source)
    photo.alternatives, photo.processing = ProcessingService._encode(
        original, [1080], 1080, ProcessingService._format, ProcessingService._quality, ProcessingService._tilt
    )

    async def _save() -> int:
        async def _write(session) -> int:
            session.add(photo)
            await session.commit()

            return photo.id

        return await DatabaseService.execute(_write)

    photo.id = app.db(_save())

    return photo


async def _load_photo(photo_id: int) -> Photo | None:
    async def _get(session) -> Photo | None:
        return (await session.execute(select(Photo).where(Photo.id == photo_id))).scalar_one_or_none()

    return await DatabaseService.execute(_get)


async def _find_photo(path: str) -> Photo | None:
    async def _get(session) -> Photo | None:
        return (await session.execute(select(Photo).where(Photo.path == path))).scalar_one_or_none()

    return await DatabaseService.execute(_get)


def _wait_for(predicate, timeout: float = 15.0, interval: float = 0.05):
    """Poll a condition while the pipeline thread processes the queued photos."""
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        result = predicate()

        if result:
            return result

        time.sleep(interval)

    raise AssertionError("timed out waiting for the pipeline")


def _stored_photo(tmp_path, filename: str, content: bytes) -> Photo:
    """Write an original into the photos folder and return its unsaved Photo row."""
    _, photos = _folders(tmp_path)
    photos.mkdir(parents=True, exist_ok=True)
    original = photos / filename
    original.write_bytes(content)

    return Photo(path=filename, filename=filename, file_size=original.stat().st_size, source="File")


async def _generate_thumbnails(photo: Photo) -> list[Path]:
    return ThumbnailService.generate_all(photo)


class TestProcessedStorage:
    @allure.title("Deletes every processed file of a photo, tolerating missing ones")
    def test_delete_alternatives(self, tmp_path):
        folder_old = ProcessingService._folder
        ProcessingService._folder = tmp_path / "processed"
        ProcessingService._folder.mkdir(parents=True)
        try:
            existing = ProcessingService._folder / "a_1080.webp"
            existing.write_bytes(b"x")
            photo = Photo(
                path="a.jpg",
                alternatives=[
                    {"target_size": 1080, "path": "a_1080.webp", "main": True},
                    {"target_size": 400, "path": "a_400.webp"},
                ],
            )

            ProcessingService.delete_alternatives(photo)

            assert not existing.exists()
        finally:
            ProcessingService._folder = folder_old

    @allure.title("Delete is a no-op when the processed file is missing")
    def test_delete_missing_file(self, tmp_path):
        ProcessingService.delete_file(tmp_path / "gone.webp")


class TestProcessingService:
    @allure.title("Generates the configured alternative for an original")
    def test_preprocess_generates_alternative(self, app, tmp_path):
        processed, _ = _folders(tmp_path)
        photo = _stored_photo(tmp_path, "shot.png", _image())

        changed = app.db(ProcessingService.preprocess(photo))

        assert changed is True
        assert len(photo.alternatives) == 1

        entry = photo.alternatives[0]
        assert entry["target_size"] == 1080
        assert entry["main"] is True
        assert (processed / entry["path"]).is_file()
        assert photo.main().path == entry["path"]
        assert photo.main().target_size == 1080

        output = next(step for step in photo.processing if step["step"] in {"downscale", "transcode"})
        assert output["summary"] == f"{entry['width']} × {entry['height']}"
        assert output["details"] == {"Target size": "1080 px", "Format": "WEBP", "Quality": "90"}
        assert output["meta"] == {}

    @allure.title("Straightens a tilted horizon, records it and keeps the original untouched")
    def test_preprocess_corrects_tilt(self, app, tmp_path):
        processed, photos = _folders(tmp_path)
        photo = _stored_photo(tmp_path, "tilted.png", _tilted_image())

        app.db(ProcessingService.preprocess(photo))
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
        photo = _stored_photo(tmp_path, "flat.png", _tilted_image())

        try:
            app.db(ProcessingService.preprocess(photo))
        finally:
            ProcessingService._tilt = previous

        assert photo.alternatives[0]["width"] == 900
        assert all(step["step"] != "tilt" for step in photo.processing)

    @allure.title("Preprocessing leaves remote photos and existing alternatives alone")
    def test_preprocess_is_a_noop_when_not_applicable(self, app, tmp_path):
        alternatives = [{"target_size": 1080, "path": "a_1080.webp", "main": True}]

        assert app.db(ProcessingService.preprocess(Photo(path="a.jpg", source="Remote"))) is False
        assert app.db(ProcessingService.preprocess(Photo(path="a.jpg", alternatives=alternatives))) is False

    @allure.title("The processing scanner gates remote photos and existing alternatives")
    def test_processing_scanner_gating(self):
        from trailframe.services.scanners.processing_scanner import ProcessingScanner

        scanner = ProcessingScanner()

        assert scanner.accept_(Photo(path="a.jpg", source="File")) is True
        assert scanner.accept_(Photo(path="a.jpg", source="Remote")) is False
        assert scanner.accept_(Photo(path="a.jpg", alternatives=[{"path": "a_1080.webp"}])) is False

    @allure.title("An upload is stored by the folder service and processed by the pipeline")
    def test_upload_flows_through_pipeline(self, app, tmp_path):
        processed, photos = _folders(tmp_path)

        path = app.db(FolderService.upload("shot.png", Upload(_image())))

        assert path == photos / "shot.png"
        assert (photos / "shot.png").is_file()

        def _processed_photo():
            photo = app.db(_find_photo("shot.png"))
            return photo if photo is not None and photo.alternatives else None

        photo = _wait_for(_processed_photo)
        entry = photo.alternatives[0]

        assert entry["target_size"] == 1080
        assert entry["main"] is True
        assert (processed / entry["path"]).is_file()
        assert photo.main().path == entry["path"]

    @allure.title("Keeps earlier originals and gives a repeated upload a unique name")
    def test_upload_keeps_existing_originals(self, app, tmp_path):
        processed, photos = _folders(tmp_path)

        first = app.db(FolderService.upload("shot.png", Upload(_image())))
        second = app.db(FolderService.upload("shot.png", Upload(_image())))

        assert first.name == "shot.png"
        assert second.name == "shot_1.png"
        assert len(list(photos.glob("shot*.png"))) == 2

        _wait_for(lambda: len(list(processed.glob("shot*.webp"))) == 2)

    @allure.title("Imports an original left behind in the photos folder")
    def test_scan_processes_leftover_originals(self, app, tmp_path):
        processed, photos = _folders(tmp_path)
        photos.mkdir(parents=True, exist_ok=True)
        (photos / "left.png").write_bytes(_image())

        app.db(FolderService.scan())

        _wait_for(lambda: len(list(processed.glob("left*.webp"))) == 1)
        assert _wait_for(lambda: app.db(_find_photo("left.png"))) is not None

    @allure.title("Does not import an original that was already processed")
    def test_scan_skips_already_processed_originals(self, app, tmp_path):
        processed, _ = _folders(tmp_path)

        app.db(FolderService.upload("shot.png", Upload(_image())))
        _wait_for(lambda: len(list(processed.glob("shot*.webp"))) == 1)

        app.db(FolderService.scan())
        time.sleep(0.3)

        assert len(list(processed.glob("shot*.webp"))) == 1

        async def _count() -> int:
            from sqlalchemy import func

            async def _query(session) -> int:
                result = await session.execute(
                    select(func.count()).select_from(Photo).where(Photo.path == "shot.png")
                )
                return result.scalar_one()

            return await DatabaseService.execute(_query)

        assert app.db(_count()) == 1

    @allure.title("Falls back to the original when a photo has no alternatives")
    def test_legacy_photo_main_is_original(self):
        photo = Photo(path="legacy.jpg", filename="legacy.jpg")

        assert photo.main().is_original is True
        assert photo.main().path == "legacy.jpg"
        assert photo.alternative(1080) is None

    @allure.title("Reprocessing swaps the alternatives and removes the previous files")
    def test_reprocess_regenerates_alternatives(self, app, tmp_path):
        processed, photos = _folders(tmp_path)
        photo = _seed_photo(app, tmp_path)
        previous = {entry["path"] for entry in photo.alternatives}

        app.db(ProcessingService.reprocess(photo.id, alternatives=[320, 640], main_target=320, rescan=False))

        entry = app.db(_load_photo(photo.id))
        targets = {item["target_size"]: item for item in entry.alternatives}

        assert set(targets) == {320, 640}
        assert targets[320]["main"] is True
        assert targets[640]["main"] is False
        assert targets[640]["width"] == 640
        assert entry.main().target_size == 320
        assert all(not (processed / path).exists() for path in previous)
        assert all((processed / item["path"]).is_file() for item in entry.alternatives)
        assert (photos / photo.path).is_file()

    @allure.title("Reprocessing without a rescan keeps the pixel-derived analysis")
    def test_reprocess_without_rescan_keeps_analysis(self, app, tmp_path):
        photo = _seed_photo(app, tmp_path)

        async def _mark() -> None:
            async def _write(session) -> None:
                stored = (await session.execute(select(Photo).where(Photo.id == photo.id))).scalar_one()
                stored.scanners = ["EXIF", "Object", "PerceptualHash"]
                stored.objects = {"detections": [{"label": "car"}]}
                stored.phash = b"12345678"
                await session.commit()

            await DatabaseService.execute(_write)

        app.db(_mark)
        app.db(ProcessingService.reprocess(photo.id, rescan=False))

        entry = app.db(_load_photo(photo.id))

        assert entry.scanners == ["EXIF", "Object", "PerceptualHash"]
        assert entry.objects == {"detections": [{"label": "car"}]}
        assert entry.phash == b"12345678"

    @allure.title("Rescanning clears the pixel-derived analysis and its scanner markers")
    def test_reset_analysis(self):
        photo = Photo(
            id=1,
            path="shot.jpg",
            scanners=["EXIF", "Object", "PerceptualHash", "Rules"],
            objects={"detections": [{"label": "car"}]},
            phash=b"12345678",
        )

        ProcessingService._reset_analysis(photo)

        assert photo.scanners == ["EXIF", "Rules"]
        assert photo.objects == {}
        assert photo.phash is None

    @allure.title("A manual angle overrides detection and is recorded as such")
    def test_reprocess_manual_tilt(self, app, tmp_path):
        photo = _seed_photo(app, tmp_path)

        app.db(
            ProcessingService.reprocess(
                photo.id, alternatives=[1080], main_target=1080, tilt=TiltOverride(angle=5.0), rescan=False
            )
        )

        entry = app.db(_load_photo(photo.id))
        tilt = next(step for step in entry.processing if step["step"] == "tilt")

        assert tilt["details"]["Detection method"] == "manual"
        assert tilt["details"]["Applied"] == "Yes"
        assert tilt["summary"] == "+5.00°"
        assert tilt["meta"]["crop_mode"] == "maximum_valid_rectangle"
        assert "line" not in tilt["meta"]

    @allure.title("A manual angle can be applied without detection")
    def test_reprocess_tilt_off(self, app, tmp_path):
        photo = _seed_photo(app, tmp_path)

        app.db(
            ProcessingService.reprocess(
                photo.id, alternatives=[1080], main_target=1080, tilt=TiltOverride(enabled=False), rescan=False
            )
        )

        entry = app.db(_load_photo(photo.id))

        assert all(step["step"] != "tilt" for step in entry.processing)
        assert entry.alternatives[0]["width"] == 1080

    @allure.title("Reprocessing replaces the thumbnails of the main target")
    def test_reprocess_invalidates_thumbnails(self, app, tmp_path):
        photo = _seed_photo(app, tmp_path)
        generated = app.db(_generate_thumbnails(photo))

        assert all(path.is_file() for path in generated)

        app.db(ProcessingService.reprocess(photo.id, alternatives=[1080], main_target=1080, rescan=False))

        assert all(not path.exists() for path in generated)

    @allure.title("A photo cannot be reprocessed twice at the same time")
    def test_reprocess_rejects_concurrent_requests(self, app, tmp_path):
        photo = _seed_photo(app, tmp_path)
        ProcessingService._reprocessing.add(photo.id)

        try:
            with pytest.raises(ReprocessError) as error:
                app.db(ProcessingService.reprocess(photo.id, rescan=False))
        finally:
            ProcessingService._reprocessing.discard(photo.id)

        assert error.value.status_code == 409

    @allure.title("Reprocessing rejects options that cannot be honoured")
    def test_reprocess_validates_options(self, app, tmp_path):
        photo = _seed_photo(app, tmp_path)
        remote = _seed_photo(app, tmp_path, filename="remote.png", source="Remote")

        with pytest.raises(ReprocessError) as unknown_main:
            app.db(ProcessingService.reprocess(photo.id, alternatives=[320], main_target=640, rescan=False))

        with pytest.raises(ReprocessError) as bad_size:
            app.db(ProcessingService.reprocess(photo.id, alternatives=[16], rescan=False))

        with pytest.raises(ReprocessError) as bad_angle:
            app.db(ProcessingService.reprocess(photo.id, tilt=TiltOverride(angle=90.0), rescan=False))

        with pytest.raises(ReprocessError) as no_original:
            app.db(ProcessingService.reprocess(remote.id, rescan=False))

        with pytest.raises(ReprocessError) as missing:
            app.db(ProcessingService.reprocess(999_999, rescan=False))

        assert unknown_main.value.status_code == 400
        assert bad_size.value.status_code == 400
        assert bad_angle.value.status_code == 400
        assert no_original.value.status_code == 422
        assert missing.value.status_code == 404


class TestReprocessAPI:
    @allure.title("Reprocessing a photo returns its updated detail")
    def test_reprocess_endpoint(self, app, tmp_path):
        photo = _seed_photo(app, tmp_path)

        response = app.post(
            f"/api/photos/{photo.id}/reprocess", json={"alternatives": [640, 320], "main": 320, "rescan": False}
        )

        assert response.status_code == 200
        body = response.json()
        assert {entry["target_size"] for entry in body["alternatives"]} == {320, 640}
        assert next(entry for entry in body["alternatives"] if entry["main"])["target_size"] == 320

    @allure.title("The reprocess endpoint rejects unknown photos and malformed options")
    def test_reprocess_endpoint_errors(self, app, tmp_path):
        photo = _seed_photo(app, tmp_path)

        missing = app.post("/api/photos/999999/reprocess", json={})
        bad_main = app.post(
            f"/api/photos/{photo.id}/reprocess", json={"alternatives": [320], "main": 640, "rescan": False}
        )
        manual_without_angle = app.post(
            f"/api/photos/{photo.id}/reprocess", json={"tilt": {"mode": "manual"}, "rescan": False}
        )
        unknown_mode = app.post(
            f"/api/photos/{photo.id}/reprocess", json={"tilt": {"mode": "sideways"}, "rescan": False}
        )

        assert missing.status_code == 404
        assert bad_main.status_code == 400
        assert manual_without_angle.status_code == 400
        assert unknown_mode.status_code == 400
