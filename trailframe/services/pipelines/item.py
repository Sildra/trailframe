from PIL import Image

from trailframe.models.photo import Photo
from trailframe.services.photos.photo_service import PhotoService


class Item:
    """Wrapper carrying a Photo plus per-pipeline-run state (updated flag and cached bitmap)."""

    def __init__(self, photo: Photo):
        self.photo = photo
        self.updated = False
        self._image: Image.Image | None = None

    @property
    def image(self) -> Image.Image | None:
        if not self._image:
            try:
                self._image = Image.open(PhotoService.resolve(self.photo))
            except OSError:
                self._image = None

        return self._image

    def close(self) -> None:
        if self._image:
            self._image.close()
            self._image = None
