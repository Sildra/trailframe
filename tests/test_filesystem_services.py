from __future__ import annotations

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

    @allure.title("Builds a hashed-by-prefix thumbnail path including the file size")
    def test_path_with_file_size(self):
        path = ThumbnailService._path_for("myphoto.jpg", 123, 400)
        assert path.relative_to(ThumbnailService._folder) == Path("my") / "myphoto.jpg_123_400.webp"

    @allure.title("Builds a thumbnail path without a file size suffix")
    def test_path_without_file_size(self):
        path = ThumbnailService._path_for("myphoto.jpg", None, 160)
        assert path.relative_to(ThumbnailService._folder) == Path("my") / "myphoto.jpg_160.webp"

    @allure.title("Sanitizes unsafe characters out of thumbnail filenames")
    def test_safe_name_strips_invalid_chars(self):
        assert ThumbnailService._safe_name('a<b>c:"d/e') == "a_b_c__d_e"
        assert ThumbnailService._safe_name("") == "photo"

    @allure.title("Uses the largest configured size by default")
    def test_get_thumbnail_path_uses_last_size_by_default(self):
        ThumbnailService._sizes = [160, 400]
        path = ThumbnailService.get_thumbnail_path(Photo(filename="x.jpg", file_size=9))
        assert path.name == "x.jpg_9_400.webp"


class TestFolderService:
    @allure.title("Resolves an absolute path as-is, ignoring the photos folder")
    def test_resolve_absolute_path_ignores_folder(self, tmp_path):
        absolute = tmp_path / "a.jpg"
        absolute.write_bytes(b"x")
        assert FolderService.resolve(absolute) == absolute

    @allure.title("Returns a relative path unchanged when no photos folder is configured")
    def test_resolve_relative_when_no_folder(self, tmp_path, monkeypatch):
        target = tmp_path / "in_cwd.jpg"
        target.write_bytes(b"x")
        monkeypatch.chdir(tmp_path)
        # With no photos folder configured, the stored path is returned unchanged.
        assert FolderService.resolve("in_cwd.jpg") == Path("in_cwd.jpg")

    @allure.title("Recognizes image files by extension, case-insensitively")
    def test_is_image(self, tmp_path):
        jpg = tmp_path / "a.JPG"
        jpg.write_bytes(b"x")
        assert FolderService._is_image(jpg) is True
        txt = tmp_path / "a.txt"
        txt.write_bytes(b"x")
        assert FolderService._is_image(txt) is False

    @allure.title("Canonicalizes a nested photo path relative to the photos folder")
    def test_canonical_relative_to_photo_folder(self, tmp_path):
        photos = tmp_path / "photos"
        photos.mkdir()
        folder_old = FolderService._folder
        FolderService._folder = photos
        try:
            photo = photos / "sub" / "x.jpg"
            photo.parent.mkdir()
            photo.write_bytes(b"x")
            assert FolderService.canonical(str(photo)) == "sub/x.jpg"
        finally:
            FolderService._folder = folder_old

    @allure.title("Canonicalizes an absolute photo path to the photos folder root")
    def test_canonical_absolute_inside_photo_folder(self, tmp_path):
        photos = tmp_path / "photos"
        photos.mkdir()
        folder_old = FolderService._folder
        FolderService._folder = photos
        try:
            photo = photos / "x.jpg"
            photo.write_bytes(b"x")
            assert FolderService.canonical(str(photo)) == "x.jpg"
        finally:
            FolderService._folder = folder_old


class TestFolderServiceEdges:
    @allure.title("Resolves a legacy CWD-relative path when it exists on disk")
    def test_resolve_legacy_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "legacy.jpg"
        target.write_bytes(b"x")
        folder_old = FolderService._folder
        FolderService._folder = tmp_path / "photos"
        try:
            assert FolderService.resolve("legacy.jpg") == target
        finally:
            FolderService._folder = folder_old

    @allure.title("Keeps the path as-is when no photos folder is configured")
    def test_canonical_without_folder(self):
        folder_old = FolderService._folder
        FolderService._folder = None
        try:
            assert FolderService.canonical("a/b.jpg") == "a/b.jpg"
        finally:
            FolderService._folder = folder_old

    @allure.title("Does not treat a directory as an image file")
    def test_is_image_ignores_directories(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        assert FolderService._is_image(tmp_path) is False

    @allure.title("Delete is a no-op when the source file is missing")
    def test_delete_missing_source(self, tmp_path):
        folder_old = FolderService._folder
        trash_old = FolderService._trash_folder
        FolderService._folder = tmp_path / "photos"
        FolderService._trash_folder = tmp_path / "trash"
        try:
            FolderService.delete(tmp_path / "photos" / "gone.jpg")
            assert not (tmp_path / "trash").exists()
        finally:
            FolderService._folder = folder_old
            FolderService._trash_folder = trash_old

    @allure.title("Delete disambiguates an existing trash name by file size")
    def test_delete_trash_conflict(self, tmp_path):
        source = tmp_path / "photos" / "dup.jpg"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"photo-content")
        trash = tmp_path / "trash"
        trash.mkdir(parents=True, exist_ok=True)
        (trash / "dup.jpg").write_bytes(b"old")

        folder_old = FolderService._folder
        trash_old = FolderService._trash_folder
        FolderService._folder = tmp_path / "photos"
        FolderService._trash_folder = trash
        FolderService._known_files.add(source)
        try:
            size = source.stat().st_size
            FolderService.delete(source)
            assert not source.exists()
            assert (trash / f"dup_{size}.jpg").exists()
        finally:
            FolderService._folder = folder_old
            FolderService._trash_folder = trash_old
            FolderService._known_files.discard(source)

    @allure.title("Forget removes a path from the known set")
    def test_forget(self):
        from pathlib import Path

        target = Path("x.jpg")
        FolderService._known_files.add(target)
        try:
            FolderService.forget(target)
            assert target not in FolderService._known_files
        finally:
            FolderService._known_files.discard(target)


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
