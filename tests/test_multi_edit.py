from __future__ import annotations

from datetime import datetime
from io import BytesIO

import allure
from PIL import Image
from sqlalchemy import select

from trailframe.models.photo import Photo


def _add_photos(app, photos: list[Photo]) -> list[int]:
    async def _insert():
        from trailframe.services.core.database_service import DatabaseService

        async def _op(session):
            for photo in photos:
                session.add(photo)
            await session.commit()
            return [photo.id for photo in photos]

        return await DatabaseService.execute(_op)

    return app.db(_insert())


def _objects(label: str) -> dict:
    return {
        "reference": {"width": 640, "height": 480},
        "detections": [{"label": label, "confidence": 0.9, "box": [10, 10, 110, 110], "surface": 0.25}],
    }


def _seed_photo(app, tmp_path, name: str) -> Photo:
    from trailframe.services.core.database_service import DatabaseService

    photos = tmp_path / "data" / "photos"
    photos.mkdir(parents=True, exist_ok=True)
    original = photos / name

    buffer = BytesIO()
    Image.new("RGB", (640, 480), (30, 90, 150)).save(buffer, format="PNG")
    original.write_bytes(buffer.getvalue())

    photo = Photo(
        path=name, filename=name, file_size=original.stat().st_size, date=datetime(2024, 5, 1, 12, 0, 0), source="File"
    )

    async def _save() -> int:
        async def _write(session):
            session.add(photo)
            await session.commit()
            return photo.id

        return await DatabaseService.execute(_write)

    photo.id = app.db(_save())
    return photo


def _processing(photo_id: int, app) -> list[dict]:
    async def _read() -> list[dict]:
        from trailframe.services.core.database_service import DatabaseService

        async def _op(session):
            stored = (await session.execute(select(Photo).where(Photo.id == photo_id))).scalar_one()
            return stored.processing or []

        return await DatabaseService.execute(_op)

    return app.db(_read())


class TestSimilarCandidates:
    @allure.title("Similarity candidates use a relative time window, objects and perceptual hash")
    def test_similar_candidates(self, app):
        ids = _add_photos(
            app,
            [
                Photo(
                    path="seed.jpg",
                    filename="seed.jpg",
                    date=datetime(2024, 5, 1, 12, 0, 0),
                    phash=(1).to_bytes(8, "big"),
                    objects=_objects("dog"),
                ),
                Photo(
                    path="near.jpg",
                    filename="near.jpg",
                    date=datetime(2024, 5, 1, 12, 20, 0),
                    phash=(1 ^ 0b1100).to_bytes(8, "big"),
                    objects=_objects("dog"),
                ),
                Photo(
                    path="different.jpg",
                    filename="different.jpg",
                    date=datetime(2024, 5, 1, 12, 30, 0),
                    phash=(0xFFFF_FFFF_FFFF_FFFF).to_bytes(8, "big"),
                    objects=_objects("airplane"),
                ),
                Photo(
                    path="far.jpg",
                    filename="far.jpg",
                    date=datetime(2024, 5, 2, 12, 0, 0),
                    phash=(1).to_bytes(8, "big"),
                    objects=_objects("dog"),
                ),
            ],
        )

        response = app.post(
            "/api/photos/similar-candidates",
            json={"photo_id": ids[0], "window_seconds": 3600, "max_hamming": 12, "min_object_overlap": 0.4},
        )

        assert response.status_code == 200
        body = response.json()
        assert [entry["photo"]["id"] for entry in body] == ids[:3]
        assert body[0]["photo"]["id"] == ids[0]
        assert body[1]["similar"] is True
        assert body[1]["phash_distance"] == 2
        assert body[1]["shared_objects"] == ["dog"]
        assert body[2]["similar"] is False

    @allure.title("Similarity rejects a seed without a capture date")
    def test_similar_candidates_without_date(self, app):
        photo_id = _add_photos(app, [Photo(path="undated.jpg", filename="undated.jpg")])[0]

        response = app.post(
            "/api/photos/similar-candidates",
            json={"photo_id": photo_id, "window_seconds": 3600, "max_hamming": 12, "min_object_overlap": 0.4},
        )

        assert response.status_code == 422


class TestBatchReprocess:
    @allure.title("Batch reprocessing applies the shared overrides to every selected photo")
    def test_reprocess_batch(self, app, tmp_path):
        first = _seed_photo(app, tmp_path, f"batch-a-{tmp_path.name}.png")
        second = _seed_photo(app, tmp_path, f"batch-b-{tmp_path.name}.png")

        response = app.post(
            "/api/photos/reprocess-batch",
            json={
                "photo_ids": [first.id, second.id],
                "options": {
                    "alternatives": [320],
                    "main": 320,
                    "rescan": False,
                    "exposure": {"enabled": True, "exposure": 1, "gamma": 1.2},
                },
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert [entry["photo_id"] for entry in body] == [first.id, second.id]
        assert all(entry["error"] is None for entry in body)

        for photo_id in (first.id, second.id):
            exposure = next(step for step in _processing(photo_id, app) if step["step"] == "exposure")
            assert exposure["meta"]["exposure"] == 1
            assert exposure["meta"]["gamma"] == 1.2

    @allure.title("Batch reprocessing reports per-photo failures")
    def test_reprocess_batch_partial_failure(self, app, tmp_path):
        photo = _seed_photo(app, tmp_path, f"batch-partial-{tmp_path.name}.png")

        response = app.post(
            "/api/photos/reprocess-batch",
            json={"photo_ids": [photo.id, 999999], "options": {"alternatives": [320], "main": 320, "rescan": False}},
        )

        assert response.status_code == 200
        body = response.json()
        assert body[0]["photo"]["id"] == photo.id
        assert body[0]["error"] is None
        assert body[1]["photo"] is None
        assert "not found" in (body[1]["error"] or "").lower()
