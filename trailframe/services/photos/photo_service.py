from pathlib import Path
from typing import ClassVar, Protocol

from trailframe.models.photo import Photo
from trailframe.models.photo_file import PhotoFile
from trailframe.services.core.configuration_service import Node
from trailframe.services.photos.folder_service import FolderService
from trailframe.services.photos.processing_service import ProcessingService
from trailframe.services.service import Service


class PhotoProvider(Protocol):
    """Storage backend for photo originals (filesystem, network, NAS, ...)."""

    SOURCE: ClassVar[str]

    @classmethod
    def resolve(cls, stored: str | Path) -> Path:
        """Absolute filesystem location for a stored original path."""

    @classmethod
    def delete(cls, path: Path) -> None:
        """Remove or archive the original file."""


class RemoteProvider:
    """In-memory photo source with no file on disk; resolution is a no-op."""

    SOURCE: ClassVar[str] = "Remote"

    @classmethod
    def resolve(cls, stored: str | Path) -> Path:
        return Path(stored)

    @classmethod
    def delete(cls, path: Path) -> None:
        return None


class PhotoService(Service):
    """Routes photo file operations to the storage that owns each file.

    Originals belong to the provider matching `Photo.source`; processed
    alternatives always live in the folder owned by `FolderService`.
    """

    _requires = ("DatabaseService",)
    _providers: ClassVar[dict[str, type[PhotoProvider]]] = {}

    @classmethod
    def _configure(cls, config: Node) -> None:
        cls.register(ProcessingService)
        cls.register(RemoteProvider)

    @classmethod
    def register(cls, provider: type[PhotoProvider]) -> None:
        cls._providers[provider.SOURCE] = provider

    @classmethod
    def provider(cls, photo: Photo) -> type[PhotoProvider]:
        return cls._providers.get(photo.source or "", ProcessingService)

    @classmethod
    def resolve(cls, photo: Photo, file: PhotoFile | None = None) -> Path:
        """Absolute location of a photo file, the main alternative by default."""
        file = file or photo.main()

        if file.is_original:
            provider = cls.provider(photo)
            return provider.resolve(file.path)

        return FolderService.resolve(file.path)

    @classmethod
    def delete(cls, photo: Photo) -> None:
        """Discard processed files and move the original to the trash."""
        FolderService.delete_alternatives(photo)
        provider = cls.provider(photo)
        provider.delete(provider.resolve(photo.path))
