from __future__ import annotations

import allure
from PIL import Image

from trailframe.models.photo import Photo
from trailframe.services.pipelines.item import Item


class TestItemImage:
    @allure.title("Lazily loads the image once and caches it")
    def test_image_cached_after_first_load(self, tmp_path):
        source = tmp_path / "img.jpg"
        source.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (20, 20)).save(source, format="JPEG")

        item = Item(Photo(path=str(source)))
        first = item.image
        second = item.image

        assert first is second
        assert first is not None

    @allure.title("Returns None when the source file cannot be decoded")
    def test_image_none_on_failure(self, tmp_path):
        missing = tmp_path / "missing.jpg"
        item = Item(Photo(path=str(missing)))

        assert item.image is None
        # Second access reuses the cached negative result (no re-read).
        assert item.image is None

    @allure.title("Starts with no pending database change")
    def test_updated_false_by_default(self):
        item = Item(Photo(path="x.jpg"))
        assert item.updated is False
