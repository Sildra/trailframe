from PIL import Image

from trailframe.models.photo import Photo
from trailframe.models.photo_file import PhotoFile
from trailframe.services.photos.photo_service import PhotoService


class Item:
    """Wrapper carrying a Photo plus per-pipeline-run state (updated flag and cached bitmaps)."""

    def __init__(self, photo: Photo, image: Image.Image | None = None):
        self.photo = photo
        self.updated = False
        self.phash_changed = False
        self._image = image
        self._original = None

    @property
    def image(self) -> Image.Image | None:
        """The pixels pipelines analyse: the main alternative, or the original."""
        if self._image is None:
            self._image = self._open(self.photo.main())

        return self._image

    @property
    def original(self) -> Image.Image | None:
        """The original archive pixels, used for EXIF and other source metadata."""
        main = self.photo.main()
        original = self.photo.original

        if main.is_original or (main.kind == original.kind and main.path == original.path):
            return self.image

        if self._original is None:
            self._original = self._open(original)

        return self._original

    def _open(self, file: PhotoFile) -> Image.Image | None:
        try:
            return Image.open(PhotoService.resolve(self.photo, file))
        except OSError:
            return None

    def close(self) -> None:
        images = {id(image): image for image in (self._image, self._original) if image is not None}

        for image in images.values():
            image.close()

        self._image = None
        self._original = None
