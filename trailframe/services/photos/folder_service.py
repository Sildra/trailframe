from pathlib import Path
from typing import ClassVar

from trailframe.models.photo import Photo
from trailframe.services.core.configuration_service import Node
from trailframe.services.service import Service


class FolderService(Service):
    """Processed storage: the folder where preprocessed alternatives are written.

    Only `ProcessingService` writes here; the folder is never scanned. Everything
    it contains is derived from an original and can be regenerated.
    """

    IMAGE_EXTENSIONS: ClassVar[set[str]] = {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".bmp"}

    _reconfig_safe = False
    _requires = ("DatabaseService",)

    _folder: Path | None = None

    @classmethod
    def _configure(cls, config: Node) -> None:
        general_node = config.get_node("general", "General parameters")
        cls._folder = Path(
            general_node.get_path_value("processed_folder", "Folder where processed photos are stored", "processed")
        )
        cls._folder.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get_folder(cls) -> Path:
        """The processed folder, where preprocessed alternatives live."""
        if cls._folder is None:
            raise RuntimeError("FolderService is not configured")

        return cls._folder

    @classmethod
    def resolve(cls, stored: str | Path) -> Path:
        """Absolute location of an alternative path stored relative to the processed folder."""
        path = Path(stored)

        if path.is_absolute() or cls._folder is None:
            return path

        return cls._folder / path

    @classmethod
    def delete_file(cls, path: Path) -> None:
        """Remove a processed file, tolerating an already missing one."""
        path.unlink(missing_ok=True)

    @classmethod
    def delete_alternatives(cls, photo: Photo) -> None:
        """Remove every processed file of a photo."""
        for entry in photo.alternatives or []:
            stored = entry.get("path") if isinstance(entry, dict) else None

            if stored:
                cls.delete_file(cls.resolve(stored))

    @classmethod
    def _is_image(cls, path: Path) -> bool:
        return path.is_file() and path.suffix.lower() in cls.IMAGE_EXTENSIONS
