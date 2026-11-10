from __future__ import annotations

import hashlib
from pathlib import Path

import allure
import pytest

from trailframe.models.photo import Photo
from trailframe.services.map.location_service import LocationService
from trailframe.services.photos.folder_service import FolderService
from trailframe.services.photos.thumbnail_service import ThumbnailService


class TestThumbnailSelectSize:
    @pytest.fixture(autouse=True)
    def _sizes(self):
        old = ThumbnailService._sizes
        ThumbnailService._sizes = [160, 400]
        yield
        ThumbnailService._sizes = old

    @allure.title("A missing preference picks the smallest configured size")
    def test_none_picks_smallest(self):
        assert ThumbnailService.select_size(None) == 160

    @allure.title("Matches an exact configured size")
    def test_matches_exact(self):
        assert ThumbnailService.select_size(160) == 160

    @allure.title("Picks the lowest size at or above the preference within 2x")
    def test_picks_lowest_above_within_2x(self):
        assert ThumbnailService.select_size(100) == 160
        assert ThumbnailService.select_size(200) == 400

    @allure.title("Falls back to the largest size below the preference")
    def test_falls_back_to_largest_below(self):
        assert ThumbnailService.select_size(800) == 400

    @allure.title("Falls back to the preference when no sizes are configured")
    def test_empty_sizes_fallback(self):
        ThumbnailService._sizes = []
        assert ThumbnailService.select_size(None) == 200
        assert ThumbnailService.select_size(300) == 300


class TestThumbnailPaths:
    @pytest.fixture(autouse=True)
    def _folder(self, tmp_path):
        old = ThumbnailService._folder
        ThumbnailService._folder = tmp_path / "thumbs"
        yield
        ThumbnailService._folder = old

    @allure.title("Builds a path from the original path hash and the main target")
    def test_path_uses_path_hash_and_main_target(self):
        photo = Photo(path="myphoto.jpg")
        path = ThumbnailService._path_for(photo, 400)
        digest = hashlib.sha1(b"myphoto.jpg").hexdigest()

        assert path.relative_to(ThumbnailService._folder) == Path(digest[:2]) / f"{digest}_original_400.webp"

    @allure.title("Keys the thumbnail by the main alternative's target size")
    def test_path_uses_alternative_target(self):
        photo = Photo(
            path="myphoto.jpg", alternatives=[{"target_size": 1080, "path": "myphoto_1080.webp", "main": True}]
        )
        path = ThumbnailService._path_for(photo, 160)
        digest = hashlib.sha1(b"myphoto.jpg").hexdigest()

        assert path.relative_to(ThumbnailService._folder) == Path(digest[:2]) / f"{digest}_1080_160.webp"

    @allure.title("Uses the largest configured size by default")
    def test_get_thumbnail_path_uses_last_size_by_default(self):
        ThumbnailService._sizes = [160, 400]
        photo = Photo(path="x.jpg", filename="x.jpg", file_size=9)
        path = ThumbnailService.get_thumbnail_path(photo)
        digest = hashlib.sha1(b"x.jpg").hexdigest()

        assert path.name == f"{digest}_original_400.webp"

    @allure.title("Deletes every generated thumbnail of a photo")
    def test_delete_removes_all_sizes(self):
        ThumbnailService._sizes = [160, 400]
        photo = Photo(path="x.jpg")
        paths = [ThumbnailService.get_thumbnail_path(photo, size) for size in (160, 400)]

        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")

        ThumbnailService.delete(photo)

        assert not any(path.exists() for path in paths)


class TestFolderService:
    @allure.title("Resolves an absolute path as-is, ignoring the processed folder")
    def test_resolve_absolute_path_ignores_folder(self, tmp_path):
        absolute = tmp_path / "a.jpg"
        absolute.write_bytes(b"x")
        assert FolderService.resolve(absolute) == absolute

    @allure.title("Resolves a relative path against the processed folder")
    def test_resolve_relative_to_processed_folder(self, tmp_path):
        folder_old = FolderService._folder
        FolderService._folder = tmp_path / "processed"
        try:
            assert FolderService.resolve("sub/x.jpg") == tmp_path / "processed" / "sub" / "x.jpg"
        finally:
            FolderService._folder = folder_old

    @allure.title("Returns a relative path unchanged when no processed folder is configured")
    def test_resolve_relative_when_no_folder(self):
        folder_old = FolderService._folder
        FolderService._folder = None
        try:
            assert FolderService.resolve("in_cwd.jpg") == Path("in_cwd.jpg")
        finally:
            FolderService._folder = folder_old

    @allure.title("Recognizes image files by extension, case-insensitively")
    def test_is_image(self, tmp_path):
        jpg = tmp_path / "a.JPG"
        jpg.write_bytes(b"x")
        assert FolderService._is_image(jpg) is True
        txt = tmp_path / "a.txt"
        txt.write_bytes(b"x")
        assert FolderService._is_image(txt) is False

    @allure.title("Does not treat a directory as an image file")
    def test_is_image_ignores_directories(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        assert FolderService._is_image(tmp_path) is False

    @allure.title("Deletes every processed file of a photo, tolerating missing ones")
    def test_delete_alternatives(self, tmp_path):
        folder_old = FolderService._folder
        FolderService._folder = tmp_path / "processed"
        FolderService._folder.mkdir(parents=True)
        try:
            existing = FolderService._folder / "a_1080.webp"
            existing.write_bytes(b"x")
            photo = Photo(
                path="a.jpg",
                alternatives=[
                    {"target_size": 1080, "path": "a_1080.webp", "main": True},
                    {"target_size": 400, "path": "a_400.webp"},
                ],
            )

            FolderService.delete_alternatives(photo)

            assert not existing.exists()
        finally:
            FolderService._folder = folder_old

    @allure.title("Delete is a no-op when the processed file is missing")
    def test_delete_missing_file(self, tmp_path):
        FolderService.delete_file(tmp_path / "gone.webp")


class TestLocationProjection:
    @allure.title("Mercator projection round-trips back to the original coordinate")
    def test_mercator_round_trip(self):
        lon, lat = LocationService._mercator_inverse(*LocationService._mercator(45.0, 6.0))
        assert lon == pytest.approx(6.0)
        assert lat == pytest.approx(45.0)

    @allure.title("Builds safe file names from location parts")
    def test_file_name_sanitizes_parts(self):
        assert LocationService._file_name(["Île de France", "Côte d'Azur"]) == "Île_de_France_Côte_d'Azur"
        assert LocationService._safe_part("../bad part") == "_bad_part"
        assert LocationService._safe_part("...") == "location"

    @allure.title("Renders a valid SVG document from projected paths")
    def test_render_produces_valid_svg(self):
        svg = LocationService._render([("M 0,0 L 10,10 Z", True)], level=0)
        assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg"')
        assert 'stroke-width="2.5"' in svg
        assert "rgba(0, 0, 0, 0.12)" in svg
