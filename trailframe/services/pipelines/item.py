from PIL import Image

from trailframe.models.photo import Photo
from trailframe.services.photos.photo_service import PhotoService


class Item:
    """Wrapper carrying a Photo plus per-pipeline-run state (updated flag and cached bitmap)."""

    def __init__(self, photo: Photo):
        self.photo = photo
        self.updated = False
        self._image: Image.Image | None = None
        self._image_loaded = False

    @property
    def image(self) -> Image.Image | None:
        if not self._image_loaded:
            self._image_loaded = True

            try:
                self._image = Image.open(PhotoService.resolve(self.photo))
            except OSError:
                self._image = None

        return self._image
