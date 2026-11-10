import hashlib
from pathlib import Path
from typing import ClassVar

from PIL import Image, ImageOps

from trailframe.models.photo import Photo
from trailframe.models.photo_file import PhotoFile
from trailframe.services.core.configuration_service import Node
from trailframe.services.photos.photo_service import PhotoService
from trailframe.services.service import Service


class ThumbnailService(Service):
    _reconfig_safe = False
    _requires = ("PhotoService",)

    _folder: Path | None = None
    _sizes: ClassVar[list[int]] = []

    @classmethod
    def _configure(cls, config: Node) -> None:
        general_node = config.get_node("general", "General parameters")
        cls._folder = Path(
            general_node.get_path_value("thumbnails_folder", "Folder where thumbnails are stored", "thumbnails")
        )
        cls._folder.mkdir(parents=True, exist_ok=True)
        sizes = general_node.get_path_value(
            "thumbnail_sizes", "Thumbnail heights (px) generated for each photo", [160, 400]
        )
        cls._sizes = sorted({int(size) for size in sizes})

    @classmethod
    def sizes(cls) -> list[int]:
        return list(cls._sizes)

    @classmethod
    def select_size(cls, preferred: int | None) -> int:
        """Pick the configured size for a preferred height.

        Lowest size >= preferred when it is at most twice the preferred size,
        otherwise the highest size below it; falls back to the smallest size.
        """
        if not cls._sizes:
            return preferred or 200

        if preferred is None:
            return cls._sizes[0]

        above = [size for size in cls._sizes if size >= preferred]

        if above and above[0] <= 2 * preferred:
            return above[0]

        below = [size for size in cls._sizes if size < preferred]

        return below[-1] if below else cls._sizes[0]

    @classmethod
    def generate(cls, photo: Photo, size: int) -> Path:
        thumbnail = cls.get_thumbnail_path(photo, size)

        if thumbnail.exists():
            return thumbnail

        thumbnail.parent.mkdir(parents=True, exist_ok=True)

        with Image.open(PhotoService.resolve(photo)) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((size, size))
            image.save(thumbnail, format="WEBP", quality=85)

        return thumbnail

    @classmethod
    def generate_all(cls, photo: Photo) -> list[Path]:
        return [cls.generate(photo, size) for size in cls._sizes]

    @classmethod
    def exists(cls, photo: Photo) -> bool:
        return all(cls.get_thumbnail_path(photo, size).exists() for size in cls._sizes)

    @classmethod
    def delete(cls, photo: Photo) -> None:
        """Remove every thumbnail generated for the photo."""
        for size in cls._sizes:
            cls.get_thumbnail_path(photo, size).unlink(missing_ok=True)

    @classmethod
    def get_thumbnail_path(cls, photo: Photo, size: int | None = None) -> Path:
        target = size if size is not None else (cls._sizes[-1] if cls._sizes else 200)

        return cls._path_for(photo, target)

    @classmethod
    def _path_for(cls, photo: Photo, size: int) -> Path:
        # Keyed by the original path, so thumbnails survive reprocessing of the
        # alternatives but invalidate when the main target changes.
        digest = hashlib.sha1(photo.path.encode("utf-8")).hexdigest()
        main: PhotoFile = photo.main()
        target = main.target_size if main.target_size is not None else "original"

        return cls._folder / digest[:2] / f"{digest}_{target}_{size}.webp"
