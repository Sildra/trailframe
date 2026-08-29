from __future__ import annotations

from datetime import datetime, timedelta
from typing import ClassVar

import allure
import pytest
from PIL import ExifTags, Image

from trailframe.models.activity import Activity
from trailframe.models.photo import Photo
from trailframe.services.pipelines.item import Item
from trailframe.services.scanners.activity_scanner import ActivityScanner
from trailframe.services.scanners.exif_scanner import ExifScanner
from trailframe.services.scanners.file_scanner import FileScanner
from trailframe.services.scanners.object_scanner import ObjectScanner
from trailframe.services.scanners.perceptual_hash_scanner import PerceptualHashScanner


def _make_image(path, exif_date=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (40, 40), (120, 40, 40))

    if exif_date is not None:
        exif = image.getexif()
        exif[ExifTags.Base.DateTimeOriginal] = exif_date
        image.save(path, exif=exif)
    else:
        image.save(path)

    return path


class TestFileScanner:
    @allure.title("Fills in filename and file size from the source file")
    @pytest.mark.asyncio
    async def test_fills_filename_and_size(self, tmp_path):
        source = _make_image(tmp_path / "file.jpg")
        scanner = FileScanner()
        item = Item(Photo(path=str(source)))

        result = await scanner.execute(item)

        assert result.value == "success"
        assert item.photo.filename == "file.jpg"
        assert item.photo.file_size == source.stat().st_size
        assert item.updated is True


class TestExifScanner:
    @allure.title("Extracts EXIF metadata and the capture date")
    @pytest.mark.asyncio
    async def test_extracts_exif_and_date(self, tmp_path):
        source = _make_image(tmp_path / "exif.jpg", exif_date="2023:06:01 12:34:56")
        scanner = ExifScanner()
        item = Item(Photo(path=str(source)))

        result = await scanner.execute(item)

        assert result.value == "success"
        assert item.photo.exif.get("DateTimeOriginal") == "2023:06:01 12:34:56"
        assert item.photo.date == datetime(2023, 6, 1, 12, 34, 56)
        assert item.updated is True

    @allure.title("Leaves the photo unchanged when there is no EXIF data")
    @pytest.mark.asyncio
    async def test_no_exif_no_change(self, tmp_path):
        source = _make_image(tmp_path / "plain.jpg")
        scanner = ExifScanner()
        item = Item(Photo(path=str(source)))

        await scanner.execute(item)

        assert item.photo.exif == {}
        assert item.updated is False


class TestPerceptualHashScanner:
    @allure.title("Computes a perceptual hash and records the scanner")
    @pytest.mark.asyncio
    async def test_computes_phash(self, tmp_path):
        source = _make_image(tmp_path / "hash.jpg")
        scanner = PerceptualHashScanner()
        item = Item(Photo(path=str(source)))

        result = await scanner.execute(item)

        assert result.value == "success"
        assert item.photo.phash is not None
        assert "PerceptualHash" in (item.photo.scanners or [])
        assert item.updated is True


class TestObjectScanner:
    @allure.title("Stores YOLO detections and records the scanner")
    @pytest.mark.asyncio
    async def test_stores_detections(self, tmp_path):
        scanner = ObjectScanner()

        class Tensor:
            def __init__(self, values):
                self._values = values

            def tolist(self):
                return self._values

        class Box:
            xyxy: ClassVar[list[Tensor]] = [Tensor([1.0, 2.0, 3.0, 4.0])]
            cls: ClassVar[list[int]] = [0]
            conf: ClassVar[list[float]] = [0.95]

        class Result:
            names: ClassVar[dict[int, str]] = {0: "person"}
            boxes: ClassVar[list[Box]] = [Box()]

        class Model:
            def __call__(self, path, verbose=False):
                return [Result()]

        scanner._model = Model()

        item = Item(Photo(path=str(tmp_path / "obj.jpg")))

        result = await scanner.execute(item)

        assert result.value == "success"
        assert item.photo.objects == [{"label": "person", "confidence": 0.95, "box": [1.0, 2.0, 3.0, 4.0]}]
        assert "Object" in (item.photo.scanners or [])
        assert item.updated is True


class TestActivityScanner:
    @allure.title("Assigns a GPS position by interpolating the nearest activity trace")
    @pytest.mark.asyncio
    async def test_assigns_position_from_trace(self, db_session):
        start = datetime(2023, 6, 1, 12, 0, 0)
        scanner = ActivityScanner()
        scanner.use_activity_position = True

        async def _insert():
            from trailframe.services.core.database_service import DatabaseService

            async def _op(session):
                session.add(
                    Activity(
                        start_time=start,
                        duration=3600,
                        trace=[{"time": 0, "lat": 45.0, "lon": 6.0}, {"time": 3600, "lat": 45.1, "lon": 6.1}],
                    )
                )
                await session.commit()

            await DatabaseService.execute(_op)

        await _insert()

        photo = Photo(path="a.jpg", date=start + timedelta(seconds=1800))
        item = Item(photo)

        result = await scanner.execute(item)

        assert result.value == "success"
        assert item.photo.latitude == pytest.approx(45.05)
        assert item.photo.longitude == pytest.approx(6.05)
        assert item.photo.location_source == "Activity"
        assert item.updated is True
