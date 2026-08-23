import re
from pathlib import Path

from PIL import Image

from trailframe.models.photo import Photo
from trailframe.services.configuration_service import Node
from trailframe.services.folder_service import FolderService
from trailframe.services.service import Service

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class ThumbnailService(Service):
    _folder: Path | None = None
    _sizes: list[int] = []

    @classmethod
    def _configure(cls, config: Node) -> None:
        cls._folder = Path(
            config.get_path_value("thumbnails_folder", "Folder where thumbnails are stored", "thumbnails")
        )
        cls._folder.mkdir(parents=True, exist_ok=True)
        sizes = config.get_path_value(
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

        with Image.open(FolderService.resolve(photo.path)) as image:
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
    def get_thumbnail_path(cls, photo: Photo, size: int | None = None) -> Path:
        target = size if size is not None else (cls._sizes[-1] if cls._sizes else 200)

        return cls._path_for(photo.filename, photo.file_size, target)

    @classmethod
    def _path_for(cls, filename: str | None, file_size: int | None, size: int) -> Path:
        name = cls._safe_name(filename or "photo")
        prefix = name[:2]

        if file_size is not None:
            return cls._folder / prefix / f"{name}_{file_size}_{size}.webp"

        return cls._folder / prefix / f"{name}_{size}.webp"

    @classmethod
    def _safe_name(cls, name: str) -> str:
        safe = _INVALID_FILENAME_CHARS.sub("_", name).lstrip(".").strip()

        if not safe:
            return "photo"

        return safe
