from __future__ import annotations

from datetime import datetime
from io import BytesIO

import allure
import pytest
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


class TestPhotoNear:
    @allure.title("Groups geo-tagged photos by proximity")
    def test_data_reports_near_photos(self, app):
        _add_photos(
            app,
            [
                Photo(path="a.jpg", filename="a.jpg", latitude=45.0, longitude=6.0),
                Photo(path="b.jpg", filename="b.jpg", latitude=45.001, longitude=6.001),
                Photo(path="c.jpg", filename="c.jpg", latitude=45.1, longitude=6.1),
            ],
        )

        detail = app.get("/api/photos/1/data").json()
        near = [group for group in detail["groups"] if group["name"] == "Near"]
        assert len(near) == 1
        assert near[0]["photo_ids"] == [2]
        assert [g["name"] for g in detail["groups"]] == ["Near"]

    @allure.title("Returns no Near group for photos without GPS")
    def test_data_no_near_without_gps(self, app):
        _add_photos(app, [Photo(path="a.jpg", filename="a.jpg"), Photo(path="b.jpg", filename="b.jpg")])

        detail = app.get("/api/photos/1/data").json()
        assert [g["name"] for g in detail["groups"]] == []


class TestPhotoDuplicates:
    @allure.title("Clusters near-duplicate photos across the library")
    def test_duplicates_reports_clusters(self, app):
        _add_photos(
            app,
            [
                Photo(path="a.jpg", filename="a.jpg", phash=bytes([0] * 8)),
                Photo(path="b.jpg", filename="b.jpg", phash=bytes([0] * 7 + [1])),
                Photo(path="c.jpg", filename="c.jpg", phash=bytes([0] * 6 + [1, 1])),
                Photo(path="d.jpg", filename="d.jpg", phash=bytes([255] * 8)),
            ],
        )

        response = app.get("/api/photos/duplicates")
        assert response.status_code == 200

        body = response.json()
        assert len(body) == 1
        assert body[0]["name"] == "Duplicate 1"
        assert body[0]["automatic"] is True
        assert body[0]["id"] is None
        assert body[0]["start_date"] is None
        assert body[0]["end_date"] is None
        assert body[0]["photo_ids"] == [1, 2, 3]

    @allure.title("Reports no groups when no duplicates exist")
    def test_duplicates_empty(self, app):
        _add_photos(
            app,
            [
                Photo(path="a.jpg", filename="a.jpg", phash=bytes([0] * 8)),
                Photo(path="b.jpg", filename="b.jpg", phash=bytes([255] * 8)),
            ],
        )

        body = app.get("/api/photos/duplicates").json()
        assert body == []

    @allure.title("Clusters transitively through a chain of near duplicates")
    def test_duplicates_transitive_chain(self, app):
        _add_photos(
            app,
            [
                Photo(path="a.jpg", filename="a.jpg", phash=bytes([0] * 8)),
                Photo(path="b.jpg", filename="b.jpg", phash=bytes([0] * 7 + [0x7F])),
                Photo(path="c.jpg", filename="c.jpg", phash=bytes([0] * 7 + [0xFF])),
            ],
        )

        body = app.get("/api/photos/duplicates").json()
        assert len(body) == 1
        assert sorted(body[0]["photo_ids"]) == [1, 2, 3]

    @allure.title("Ignores photos without a perceptual hash")
    def test_duplicates_ignore_unhashed(self, app):
        _add_photos(
            app,
            [
                Photo(path="a.jpg", filename="a.jpg", phash=bytes([0] * 8)),
                Photo(path="b.jpg", filename="b.jpg", phash=bytes([0] * 7 + [1])),
                Photo(path="c.jpg", filename="c.jpg"),
            ],
        )

        body = app.get("/api/photos/duplicates").json()
        assert len(body) == 1
        assert body[0]["photo_ids"] == [1, 2]

    @allure.title("Skips malformed perceptual hashes instead of failing")
    def test_duplicates_skip_malformed_phash(self, app):
        _add_photos(
            app,
            [
                Photo(path="a.jpg", filename="a.jpg", phash=bytes([0] * 8)),
                Photo(path="b.jpg", filename="b.jpg", phash=bytes([0] * 8 + [1])),
                Photo(path="c.jpg", filename="c.jpg", phash=b"short"),
            ],
        )

        response = app.get("/api/photos/duplicates")
        assert response.status_code == 200
        assert response.json() == []

    @allure.title("Deleting a duplicate drops it from the clusters")
    def test_duplicates_delete_removes_photo(self, app, tmp_path):
        a = _make_image(_photos_folder(tmp_path) / "a.jpg")
        b = _make_image(_photos_folder(tmp_path) / "b.jpg")
        _add_photos(
            app,
            [
                Photo(path="a.jpg", filename="a.jpg", file_size=a.stat().st_size, phash=bytes([0] * 8)),
                Photo(path="b.jpg", filename="b.jpg", file_size=b.stat().st_size, phash=bytes([0] * 7 + [1])),
            ],
        )

        assert len(app.get("/api/photos/duplicates").json()) == 1

        assert app.delete("/api/photos/1").json() == {"deleted": True}

        assert app.get("/api/photos/duplicates").json() == []

    @allure.title("New perceptual hashes are folded into the existing clusters")
    def test_duplicates_new_phash_joins_cluster(self, app):
        from trailframe.services.photos.duplicates_service import DuplicatesService

        _add_photos(
            app,
            [
                Photo(path="a.jpg", filename="a.jpg", phash=bytes([0] * 8)),
                Photo(path="c.jpg", filename="c.jpg", phash=bytes([255] * 8)),
            ],
        )

        assert app.get("/api/photos/duplicates").json() == []

        _add_photos(app, [Photo(path="b.jpg", filename="b.jpg", phash=bytes([0] * 7 + [1]))])

        DuplicatesService.mark_added(3, bytes([0] * 7 + [1]))

        body = app.get("/api/photos/duplicates").json()
        assert len(body) == 1
        assert sorted(body[0]["photo_ids"]) == [1, 3]

    @allure.title("A changed perceptual hash moves a photo into a new cluster")
    def test_duplicates_changed_phash_reclusters(self, app):
        from trailframe.services.photos.duplicates_service import DuplicatesService

        _add_photos(
            app,
            [
                Photo(path="a.jpg", filename="a.jpg", phash=bytes([0] * 8)),
                Photo(path="b.jpg", filename="b.jpg", phash=bytes([0] * 7 + [1])),
                Photo(path="c.jpg", filename="c.jpg", phash=bytes([255] * 8)),
            ],
        )

        assert len(app.get("/api/photos/duplicates").json()) == 1

        DuplicatesService.mark_added(1, bytes([255] * 8))

        body = app.get("/api/photos/duplicates").json()
        assert len(body) == 1
        assert sorted(body[0]["photo_ids"]) == [1, 3]

    @allure.title("Groups photos with estimated countries by year and country")
    def test_location_issues_estimated_countries(self, app):
        _add_photos(
            app,
            [
                Photo(path="a.jpg", filename="a.jpg", date=datetime(2023, 3, 1, 12, 0, 0), country="France"),
                Photo(path="b.jpg", filename="b.jpg", date=datetime(2023, 3, 1, 12, 30, 0)),
                Photo(path="c.jpg", filename="c.jpg", date=datetime(2023, 3, 5, 12, 0, 0)),
                Photo(path="d.jpg", filename="d.jpg", date=datetime(2024, 7, 1, 9, 0, 0), country="Spain"),
                Photo(path="e.jpg", filename="e.jpg", date=datetime(2024, 7, 1, 12, 0, 0)),
            ],
        )

        body = app.get("/api/photos/location-issues").json()

        assert len(body) == 2
        assert body[0]["name"] == "2023 - France"
        assert body[0]["automatic"] is True
        assert body[0]["id"] is None
        assert body[0]["photo_ids"] == [2]
        assert body[1]["name"] == "2024 - Spain"
        assert body[1]["photo_ids"] == [5]

    @allure.title("Flags geotagged photos that deviate from the interpolated path")
    def test_location_issues_interpolated_mismatch(self, app):
        _add_photos(
            app,
            [
                Photo(
                    path="p1.jpg",
                    filename="p1.jpg",
                    date=datetime(2023, 1, 1, 10, 0, 0),
                    country="France",
                    latitude=48.0,
                    longitude=2.0,
                ),
                Photo(
                    path="p2.jpg",
                    filename="p2.jpg",
                    date=datetime(2023, 1, 1, 10, 30, 0),
                    country="France",
                    latitude=48.0,
                    longitude=20.0,
                ),
                Photo(
                    path="p3.jpg",
                    filename="p3.jpg",
                    date=datetime(2023, 1, 1, 11, 0, 0),
                    country="France",
                    latitude=49.0,
                    longitude=4.0,
                ),
            ],
        )

        body = app.get("/api/photos/location-issues").json()

        assert len(body) == 1
        assert body[0]["name"] == "2023 - France"
        assert body[0]["photo_ids"] == [2]

    @allure.title("Reports an estimated area for photos without GPS in the detail")
    def test_location_estimate_in_photo_detail(self, app):
        _add_photos(
            app,
            [
                Photo(
                    path="a.jpg",
                    filename="a.jpg",
                    date=datetime(2023, 1, 1, 10, 0, 0),
                    country="France",
                    latitude=48.0,
                    longitude=2.0,
                ),
                Photo(
                    path="b.jpg",
                    filename="b.jpg",
                    date=datetime(2023, 1, 1, 11, 0, 0),
                    country="France",
                    latitude=49.0,
                    longitude=2.0,
                ),
                Photo(path="c.jpg", filename="c.jpg", date=datetime(2023, 1, 1, 10, 30, 0)),
            ],
        )

        detail = app.get("/api/photos/3/data").json()
        estimate = detail["location_estimate"]

        assert estimate is not None
        assert estimate["lat"] == pytest.approx(48.5, abs=0.01)
        assert estimate["lon"] == pytest.approx(2.0, abs=0.01)
        assert estimate["radius_m"] > 5000

        reference = app.get("/api/photos/1/data").json()
        assert reference["location_estimate"] is None

    @allure.title("Returns no groups when every photo has a known, consistent location")
    def test_location_issues_empty(self, app):
        _add_photos(
            app,
            [
                Photo(
                    path="a.jpg",
                    filename="a.jpg",
                    date=datetime(2023, 3, 1, 12, 0, 0),
                    country="France",
                    latitude=48.0,
                    longitude=2.0,
                ),
                Photo(
                    path="b.jpg",
                    filename="b.jpg",
                    date=datetime(2023, 3, 1, 12, 30, 0),
                    country="France",
                    latitude=49.0,
                    longitude=2.0,
                ),
            ],
        )

        assert app.get("/api/photos/location-issues").json() == []


class TestMapDataApi:
    @allure.title("Returns geo-tagged photos and activity traces")
    def test_map_data(self, app):
        photo_id = _add_photos(app, [Photo(path="m.jpg", filename="m.jpg", latitude=45.0, longitude=6.0)])[0]

        async def _add_activity():
            from trailframe.services.core.database_service import DatabaseService

            async def _op(session):
                session.add(Activity(name="Ride", trace=[[0, 45.0, 6.0], [3600, 45.1, 6.1]]))
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
