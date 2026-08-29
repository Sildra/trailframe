from __future__ import annotations

from datetime import datetime
from io import BytesIO

import allure
from PIL import Image

from trailframe.models.activity import Activity
from trailframe.models.photo import Photo


def _add_photos(app, photos):
    async def _insert():
        from trailframe.services.core.database_service import DatabaseService

        async def _op(session):
            for photo in photos:
                session.add(photo)
            await session.commit()
            return [photo.id for photo in photos]

        return await DatabaseService.execute(_op)

    return app.db(_insert())


def _photos_folder(tmp_path):
    return tmp_path / "data" / "photos"


def _make_image(path, size=(320, 240), color=(200, 60, 60)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="JPEG")
    return path


class TestCustomSlideshowFilters:
    @allure.title("Filters the custom slideshow by location substring, tags and group")
    def test_custom_filters(self, app):
        _add_photos(
            app,
            [
                Photo(
                    path="a.jpg", date=datetime(2023, 3, 1, 12, 0, 0), location="Paris, France", tags=["sunset", "sea"]
                ),
                Photo(path="b.jpg", date=datetime(2023, 3, 1, 13, 0, 0), location="London, UK", tags=["city"]),
            ],
        )

        params = {"location": "paris"}
        assert app.get("/api/photos/custom", params=params).json() == [1]

        params = {"tags": "sea"}
        assert app.get("/api/photos/custom", params=params).json() == [1]

        # Tags use AND semantics: no single photo has both sunset and city.
        params = {"tags": ["sunset", "city"]}
        assert app.get("/api/photos/custom", params=params).json() == []

        params = {"start_date": "2023-03-01", "end_date": "2023-03-01"}
        assert sorted(app.get("/api/photos/custom", params=params).json()) == [1, 2]

    @allure.title("Filters the custom slideshow by a date-bounded group")
    def test_custom_filters_by_group(self, app):
        _add_photos(
            app,
            [
                Photo(path="in.jpg", date=datetime(2023, 6, 1, 12, 0, 0)),
                Photo(path="out.jpg", date=datetime(2023, 12, 1, 12, 0, 0)),
            ],
        )

        app.post("/api/photos/groups", json={"name": "Summer", "start_date": "2023-01-01", "end_date": "2023-12-31"})

        # Both photos fall inside 2023, so both belong to the Summer group.
        ids = app.get("/api/photos/custom", params={"group": "Summer"}).json()
        assert ids == [1, 2]

        assert app.get("/api/photos/custom", params={"group": "Missing"}).json() == []


class TestPhotoFileEndpoints:
    @allure.title("Serves the original image file and 404s for a missing one")
    def test_get_image(self, app, tmp_path):
        source = _make_image(_photos_folder(tmp_path) / "img.jpg")
        photo_id = _add_photos(app, [Photo(path="img.jpg", filename="img.jpg", file_size=source.stat().st_size)])[0]

        response = app.get(f"/api/photos/{photo_id}/image")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/")

        assert app.get("/api/photos/999/image").status_code == 404

    @allure.title("Generates and serves a webp thumbnail, 404s for a missing photo")
    def test_get_thumbnail(self, app, tmp_path):
        source = _make_image(_photos_folder(tmp_path) / "thumb.jpg")
        photo_id = _add_photos(app, [Photo(path="thumb.jpg", filename="thumb.jpg", file_size=source.stat().st_size)])[0]

        response = app.get(f"/api/photos/{photo_id}/thumbnail", params={"size": 160})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/webp")

        assert app.get("/api/photos/999/thumbnail").status_code == 404

    @allure.title("Returns 404 for a photo with no wireframe")
    def test_get_wireframe_404(self, app):
        photo_id = _add_photos(app, [Photo(path="wf.jpg", filename="wf.jpg")])[0]
        assert app.get(f"/api/photos/{photo_id}/wireframe").status_code == 404

    @allure.title("Deletes a photo: moves the file and removes the row")
    def test_delete_photo(self, app, tmp_path):
        source = _make_image(_photos_folder(tmp_path) / "del.jpg")
        photo_id = _add_photos(app, [Photo(path="del.jpg", filename="del.jpg", file_size=source.stat().st_size)])[0]

        response = app.delete(f"/api/photos/{photo_id}")
        assert response.status_code == 200
        assert response.json() == {"deleted": True}
        assert not source.exists()

        assert app.get("/api/photos/count").json() == 0

    @allure.title("Uploads a photo file and records it")
    def test_upload_photo(self, app, tmp_path):
        buffer = BytesIO()
        Image.new("RGB", (20, 20)).save(buffer, format="PNG")

        response = app.post("/api/photos/upload", files={"file": ("up.png", buffer.getvalue(), "image/png")})
        assert response.status_code == 200
        assert response.json()["filename"] == "up.png"


class TestPhotoPhashSimilar:
    @allure.title("Groups near-duplicate photos by perceptual hash distance")
    def test_data_reports_similar_photos(self, app):
        _add_photos(
            app,
            [
                Photo(path="x.jpg", filename="x.jpg", phash=bytes([0] * 8)),
                Photo(path="y.jpg", filename="y.jpg", phash=bytes([0] * 7 + [1])),
                Photo(path="z.jpg", filename="z.jpg", phash=bytes([255] * 8)),
            ],
        )

        detail = app.get("/api/photos/1/data").json()
        similar = [group for group in detail["groups"] if group["name"] == "Similar"]
        assert len(similar) == 1
        assert similar[0]["photo_ids"] == [2]


class TestMapDataApi:
    @allure.title("Returns geo-tagged photos and activity traces")
    def test_map_data(self, app):
        photo_id = _add_photos(app, [Photo(path="m.jpg", filename="m.jpg", latitude=45.0, longitude=6.0)])[0]

        async def _add_activity():
            from trailframe.services.core.database_service import DatabaseService

            async def _op(session):
                session.add(Activity(name="Ride", trace=[{"lat": 45.0, "lon": 6.0}, {"lat": 45.1, "lon": 6.1}]))
                await session.commit()

            await DatabaseService.execute(_op)

        app.db(_add_activity())

        payload = app.get("/api/map-data").json()
        assert payload["photos"] == [{"id": photo_id, "lat": 45.0, "lon": 6.0}]
        assert payload["activities"][0]["name"] == "Ride"
        assert payload["activities"][0]["trace"] == [[45.0, 6.0], [45.1, 6.1]]


class TestTileAndModelApis:
    @allure.title("Rejects out-of-range tile coordinates with 404")
    def test_tile_invalid_z(self, app):
        assert app.get("/api/tiles/25/0/0.png").status_code == 404

    @allure.title("Lists installed models, empty when the folder does not exist")
    def test_list_models_empty(self, app):
        assert app.get("/api/models").json() == []

    @allure.title("Rejects downloading an unknown model name")
    def test_download_unknown_model(self, app):
        response = app.post("/api/models/nope.pt/download")
        assert response.status_code == 400


class TestConfigurationApi:
    @allure.title("Returns the current configuration as JSON")
    def test_get_configuration(self, app):
        payload = app.get("/api/configuration").json()
        assert "general" in payload["children"]
