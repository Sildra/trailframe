from __future__ import annotations

from datetime import datetime

import allure

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


class TestPhotosApi:
    @allure.title("Lists an empty photo set and returns a zero count")
    def test_empty_list_and_count(self, app):
        assert app.get("/api/photos").json() == []
        assert app.get("/api/photos/count").json() == 0

    @allure.title("Toggles favorite status and filters favorites-only listings")
    def test_favorite_flow(self, app):
        photo_id = _add_photos(
            app, [Photo(path="a.jpg", filename="a.jpg", file_size=10, date=datetime(2023, 6, 1, 12, 0, 0))]
        )[0]

        # Not a favorite by default
        assert app.get("/api/photos?favorites=true").json() == []
        assert app.get("/api/photos/favorites").json() == []

        response = app.put(f"/api/photos/{photo_id}/favorite", json={"value": True})
        assert response.status_code == 200
        assert response.json() == {"id": photo_id, "is_favorite": True}

        assert app.get("/api/photos/favorites").json() == [photo_id]
        favorite_detail = app.get("/api/photos?favorites=true").json()
        assert favorite_detail[0]["id"] == photo_id
        assert favorite_detail[0]["is_favorite"] is True

    @allure.title("Returns 404 when favoriting a missing photo")
    def test_favorite_404(self, app):
        response = app.put("/api/photos/999/favorite", json={"value": True})
        assert response.status_code == 404

    @allure.title("Returns photo detail, stripping the EXIF MakerNote")
    def test_photo_detail_strips_makernote(self, app):
        photo_id = _add_photos(
            app,
            [
                Photo(
                    path="x.jpg",
                    filename="x.jpg",
                    file_size=10,
                    date=datetime(2023, 6, 1, 12, 0, 0),
                    tags=["sunset"],
                    exif={"Make": "Nikon", "MakerNote": "secret"},
                    latitude=45.0,
                    longitude=6.0,
                )
            ],
        )[0]

        detail = app.get(f"/api/photos/{photo_id}/data").json()
        assert detail["filename"] == "x.jpg"
        assert detail["tags"] == ["sunset"]
        assert "MakerNote" not in detail["exif"]
        assert detail["exif"]["Make"] == "Nikon"

    @allure.title("Returns 404 when deleting a missing photo")
    def test_delete_photo_404(self, app):
        assert app.delete("/api/photos/999").status_code == 404


class TestGroupingsApi:
    @allure.title("Builds automatic year and no-date groups from photo dates")
    def test_groups_automatic_by_year(self, app):
        _add_photos(
            app,
            [
                Photo(path="r1.jpg", date=datetime(2022, 3, 1, 12, 0, 0)),
                Photo(path="r2.jpg", date=datetime(2023, 7, 1, 12, 0, 0)),
                Photo(path="r3.jpg", date=None),
            ],
        )

        groups = app.get("/api/photos/groups").json()
        by_name = {group["name"]: group for group in groups}

        assert by_name["2022"]["automatic"] is True
        assert by_name["2023"]["automatic"] is True
        assert by_name["No date"]["automatic"] is True
        assert len(by_name["2022"]["photo_ids"]) == 1
        assert len(by_name["No date"]["photo_ids"]) == 1

    @allure.title("Creates a date-bounded group and deletes it")
    def test_create_and_delete_group(self, app):
        _add_photos(app, [Photo(path="r1.jpg", date=datetime(2023, 3, 1, 12, 0, 0))])

        created = app.post(
            "/api/photos/groups", json={"name": "Trip", "start_date": "2023-01-01", "end_date": "2023-12-31"}
        ).json()
        assert created["name"] == "Trip"
        assert len(created["photo_ids"]) == 1
        group_id = created["id"]

        assert app.delete(f"/api/photos/groups/{group_id}").status_code == 200
        assert app.delete("/api/photos/groups/999").status_code == 404

    @allure.title("Filters custom slideshow selections by date, favorites and randomization")
    def test_custom_slideshow_filters(self, app):
        _add_photos(
            app,
            [
                Photo(path="a.jpg", date=datetime(2023, 3, 1, 12, 0, 0), is_favorite=True),
                Photo(path="b.jpg", date=datetime(2021, 1, 1, 12, 0, 0)),
            ],
        )

        ids = app.get("/api/photos/custom", params={"start_date": "2022-01-01", "end_date": "2024-01-01"}).json()
        assert len(ids) == 1

        favorite_ids = app.get("/api/photos/custom", params={"favorites": "true"}).json()
        assert len(favorite_ids) == 1

        randomized = app.get("/api/photos/custom", params={"randomize": "true"}).json()
        assert sorted(randomized) == sorted([1, 2])


class TestStatisticsApi:
    @allure.title("Returns aggregated per-scanner throughput statistics")
    def test_scanner_statistics(self, app):
        from trailframe.models.scanner_stat import ScannerStat

        async def _insert():
            from trailframe.services.core.database_service import DatabaseService

            async def _op(session):
                session.add(ScannerStat(scanner="EXIF", count=10, total_ms=1000.0))
                await session.commit()

            await DatabaseService.execute(_op)

        app.db(_insert())

        response = app.get("/api/statistics/scanners")
        assert response.status_code == 200
        assert response.json() == [{"name": "EXIF", "items": 10, "value": 10.0}]

    @allure.title("Returns the storage statistics shape for every folder")
    def test_storage_statistics_shape(self, app):
        response = app.get("/api/statistics/storage")
        assert response.status_code == 200
        payload = response.json()
        assert "database_size" in payload
        assert isinstance(payload["filesystem"], list)
        assert {entry["name"] for entry in payload["filesystem"]} >= {
            "Photos",
            "Thumbnails",
            "Maps",
            "Activities",
            "Models",
            "Tiles",
            "Trash",
        }


class TestPipelineApi:
    @allure.title("Lists the scanners known to both pipelines")
    def test_lists_known_scanners(self, app):
        scanners = app.get("/api/pipeline/scanners").json()
        assert "File" in scanners
        assert "EXIF" in scanners
        assert "Thumbnail" in scanners
        assert "PerceptualHash" in scanners

    @allure.title("Rejects a forced scan request for unknown scanners")
    def test_forced_scan_unknown_scanner(self, app):
        response = app.post("/api/pipeline/scan", json={"scanners": ["Nope"]})
        assert response.status_code == 200
        assert response.json()["status"].startswith("unknown scanners")


class TestAboutApi:
    @allure.title("Lists imported packages with name, version and license")
    def test_packages_returns_list(self, app):
        response = app.get("/api/about/packages")
        assert response.status_code == 200
        packages = response.json()
        assert isinstance(packages, list)
        assert all({"name", "version", "license"} <= set(pkg) for pkg in packages)

    @allure.title("Computes the package list once and caches it")
    def test_packages_result_is_cached(self, app, monkeypatch):
        from trailframe.api import about

        calls = 0
        original = about._build_packages

        def counting():
            nonlocal calls
            calls += 1
            return original()

        about._cached_packages = None
        monkeypatch.setattr(about, "_build_packages", counting)

        first = app.get("/api/about/packages").json()
        second = app.get("/api/about/packages").json()

        assert calls == 1
        assert first == second
