from pathlib import Path
from typing import ClassVar, Protocol

from trailframe.models.photo import Photo
from trailframe.services.core.configuration_service import Node
from trailframe.services.photos.folder_service import FolderService
from trailframe.services.service import Service


class PhotoProvider(Protocol):
    """Storage backend for photo sources (filesystem, network, NAS, ...)."""

    SOURCE: ClassVar[str]

    @classmethod
    def resolve(cls, stored: str | Path) -> Path:
        """Absolute filesystem location for a stored photo path."""

    @classmethod
    def delete(cls, path: Path) -> None:
        """Remove the source file."""


class PhotoService(Service):
    """Routes photo source operations to a provider based on the photo's source type."""

    _providers: ClassVar[dict[str, type[PhotoProvider]]] = {}

    @classmethod
    def _configure(cls, config: Node) -> None:
        cls.register(FolderService)

    @classmethod
    def register(cls, provider: type[PhotoProvider]) -> None:
        cls._providers[provider.SOURCE] = provider

    @classmethod
    def provider(cls, photo: Photo) -> type[PhotoProvider]:
        return cls._providers.get(photo.source or "", FolderService)

    @classmethod
    def resolve(cls, photo: Photo) -> Path:
        return cls.provider(photo).resolve(photo.path)

    @classmethod
    def delete(cls, photo: Photo) -> None:
        provider = cls.provider(photo)
        provider.delete(provider.resolve(photo.path))
