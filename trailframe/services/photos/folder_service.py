import asyncio
import shutil
from pathlib import Path
from typing import ClassVar

from sqlalchemy import select

from trailframe.models.photo import Photo
from trailframe.services.core.configuration_service import Node
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.service import Service


class FolderService(Service):
    SOURCE: ClassVar[str] = "File"

    IMAGE_EXTENSIONS: ClassVar[set[str]] = {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".bmp"}

    _folder: Path | None = None
    _trash_folder: Path | None = None
    _interval = 10
    _known_files: ClassVar[set[Path]] = set()
    _task: asyncio.Task | None = None
    _running = False
    _creation_throttle = 0

    @classmethod
    def resolve(cls, stored: str | Path) -> Path:
        """Absolute filesystem location for a stored photo path."""
        path = Path(stored)

        if path.is_absolute() or cls._folder is None:
            return path

        candidate = cls._folder / path

        if candidate.exists():
            return candidate

        legacy = Path.cwd() / path
        return legacy if legacy.exists() else candidate

    @classmethod
    def canonical(cls, path: str | Path) -> str:
        """Canonical storage form for a photo location: posix, relative to the photos folder.

        Accepts absolute paths, paths relative to the current CWD, and legacy
        CWD-relative strings from earlier configurations (e.g. '..\\..\\data\\photos\\x.jpg').
        """
        p = Path(path)
        folder = cls._folder

        if folder is None:
            return p.as_posix()

        candidates: list[Path] = []

        if p.is_absolute():
            candidates.append(p)
        else:
            candidates.extend([folder / p, Path.cwd() / p])

            marker = folder.name
            parts = p.parts

            if marker in parts:
                index = len(parts) - 1 - parts[::-1].index(marker)
                candidates.append(folder.joinpath(*parts[index + 1 :]))

        for candidate in candidates:
            if not candidate.is_file():
                continue

            try:
                return candidate.resolve().relative_to(folder.resolve()).as_posix()
            except ValueError:
                continue

        for candidate in candidates:
            try:
                return candidate.resolve().relative_to(folder.resolve()).as_posix()
            except ValueError:
                continue

        return p.as_posix()

    @classmethod
    def _configure(cls, config: Node) -> None:
        cls._folder = Path(config.get_path_value("photos_folder", "Folder where photos are stored", "photos"))
        cls._folder.mkdir(parents=True, exist_ok=True)
        cls._trash_folder = Path(
            config.get_path_value("trash_folder", "Folder where deleted photos are moved", "trash")
        )
        cls._trash_folder.mkdir(parents=True, exist_ok=True)
        cls._creation_throttle = config.get_path_value("creation_throttle", "Throttle items simultaneously added to the pipeline", 0)

    @classmethod
    async def _start(cls) -> None:
        if cls._folder is None:
            raise RuntimeError("FolderService is not configured")

        cls._running = True

        cls._task = asyncio.create_task(cls._watch())

    @classmethod
    async def _stop(cls) -> None:
        cls._running = False

        if cls._task:
            cls._task.cancel()
            cls._task = None

    @classmethod
    async def to_photo(cls, path: Path) -> Photo:
        """Convert a filesystem path to a Photo: look up the canonical stored path
        in the database, or create a new (unscanned) Photo for it."""
        canonical = cls.canonical(path)

        async def _lookup(session) -> Photo | None:
            result = await session.execute(select(Photo).where(Photo.path == canonical))
            return result.scalar_one_or_none()

        existing = await DatabaseService.execute(_lookup)

        if existing is not None:
            return existing

        return Photo(path=canonical, source=cls.SOURCE)

    @classmethod
    async def scan(cls) -> None:
        items = 0
        for path in cls._folder.rglob("*"):
            if not cls._is_image(path):
                continue

            if path in cls._known_files:
                continue

            items += 1
            cls._known_files.add(path)
            if cls._creation_throttle != 0:
                while PipelineService.get_queue_size() > cls._creation_throttle:
                    await asyncio.sleep(1)

            from trailframe.services.pipelines.pipeline_service import PipelineService

            await PipelineService.next(await cls.to_photo(path))
        if items != 0:
            cls._log(f"Found {items} new files")

    @classmethod
    async def upload(cls, filename: str, content) -> Path:
        destination = cls._folder / filename

        cls._known_files.add(destination)

        with destination.open("wb") as output:
            while chunk := await content.read(1024 * 1024):
                output.write(chunk)

        from trailframe.services.pipelines.pipeline_service import PipelineService

        await PipelineService.next(await cls.to_photo(destination))

        return destination

    @classmethod
    def forget(cls, path: Path) -> None:
        cls._known_files.discard(path)

    @classmethod
    def delete(cls, path: Path) -> None:
        if not path.is_file() or cls._trash_folder is None:
            return

        destination = cls._trash_folder / path.name

        if destination.exists():
            destination = cls._trash_folder / f"{path.stem}_{path.stat().st_size}{path.suffix}"

        shutil.move(str(path), str(destination))
        cls._known_files.discard(path)

    @classmethod
    async def _watch(cls) -> None:
        while cls._running:
            await asyncio.sleep(cls._interval)
            await cls.scan()

    @classmethod
    def _is_image(cls, path: Path) -> bool:
        return path.is_file() and path.suffix.lower() in cls.IMAGE_EXTENSIONS
