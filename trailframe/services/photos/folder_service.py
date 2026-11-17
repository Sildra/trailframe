import asyncio
import logging
import shutil
from pathlib import Path
from typing import ClassVar

from sqlalchemy import select

from trailframe.models.photo import Photo
from trailframe.services.core.configuration_service import Node
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.service import Service


class FolderService(Service):
    """Originals storage: the folder where uploaded photos are archived.

    Scans and watches `general.photos_folder` and pushes every new image into the
    pipelines as a `Photo`. Preprocessing and the derived alternatives happen in
    the pipeline (see `ProcessingScanner`); this service only stores originals.
    """

    SOURCE: ClassVar[str] = "File"

    IMAGE_EXTENSIONS: ClassVar[set[str]] = {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".bmp"}

    _reconfig_safe = False
    _requires = ("DatabaseService", "PipelineService")

    _folder: Path | None = None
    _trash_folder: Path | None = None
    _failsafe = False
    _interval = 10
    _known_files: ClassVar[set[str]] = set()
    _task: asyncio.Task | None = None
    _running = False
    _creation_throttle = 0
    _lock: ClassVar[asyncio.Lock | None] = None

    @classmethod
    def _configure(cls, config: Node) -> None:
        general_node = config.get_node("general", "General parameters")
        cls._folder = Path(
            general_node.get_path_value("photos_folder", "Folder where uploaded photos are stored", "photos")
        )
        cls._folder.mkdir(parents=True, exist_ok=True)
        cls._trash_folder = Path(
            general_node.get_path_value("trash_folder", "Folder where deleted photos are moved", "trash")
        )
        cls._trash_folder.mkdir(parents=True, exist_ok=True)
        cls._creation_throttle = general_node.get_path_value(
            "creation_throttle", "Throttle items simultaneously added to the pipeline", 0
        )
        cls._failsafe = general_node.get_path_value(
            "failsafe", "Start without scanning or watching the photos folder", False
        )

    @classmethod
    async def _start(cls) -> None:
        if cls._folder is None:
            raise RuntimeError("FolderService is not configured")

        if cls._failsafe:
            cls._log("failsafe: skipping folder scan and watch")
            return

        cls._running = True
        cls._task = asyncio.create_task(cls._watch())

    @classmethod
    async def _stop(cls) -> None:
        cls._running = False

        if cls._task:
            cls._task.cancel()
            cls._task = None

    @classmethod
    def get_folder(cls) -> Path:
        """The photos folder, where original files are archived."""
        if cls._folder is None:
            raise RuntimeError("FolderService is not configured")

        return cls._folder

    @classmethod
    def resolve(cls, stored: str | Path) -> Path:
        """Absolute location of an original stored relative to the photos folder.

        Falls back to a CWD-relative path for legacy rows written by earlier
        configurations.
        """
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
        """Storage form of an original: posix, relative to the photos folder.

        Accepts absolute paths, paths relative to the current CWD, and legacy
        CWD-relative strings from earlier configurations.
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
    def forget(cls, stored: str | Path) -> None:
        """Allow a file to be queued again on the next scan."""
        cls._known_files.discard(cls.canonical(stored))

    @classmethod
    def delete(cls, path: Path) -> None:
        """Move an original to the trash folder."""
        if not path.is_file() or cls._trash_folder is None:
            return

        destination = cls._trash_folder / path.name

        if destination.exists():
            destination = cls._trash_folder / f"{path.stem}_{path.stat().st_size}{path.suffix}"

        shutil.move(str(path), str(destination))
        cls._known_files.discard(cls.canonical(path))

    @classmethod
    async def to_photo(cls, path: Path) -> Photo:
        """Return the stored photo for a path, or a new unscanned one for it."""
        canonical = cls.canonical(path)

        async def _lookup(session) -> Photo | None:
            result = await session.execute(select(Photo).where(Photo.path == canonical))
            return result.scalar_one_or_none()

        existing = await DatabaseService.execute(_lookup)

        if existing is not None:
            return existing

        return Photo(path=canonical, filename=path.name, file_size=_file_size(path), source=cls.SOURCE)

    @classmethod
    async def ingest(cls, path: Path) -> Photo:
        """Queue a file already inside the photos folder for the pipelines."""
        from trailframe.services.pipelines.pipeline_service import PipelineService

        destination = path if path.is_absolute() else cls.get_folder() / path
        cls._known_files.add(cls.canonical(destination))

        photo = await cls.to_photo(destination)
        await PipelineService.next(photo)

        return photo

    @classmethod
    async def upload(cls, filename: str, content) -> Path:
        """Store an upload in the photos folder, then queue it for the pipelines."""
        if cls._folder is None:
            raise RuntimeError("FolderService is not configured")

        async with cls._get_lock():
            destination = cls._unique_path(cls._folder, Path(filename or "photo").name)
            temporary = destination.with_name(destination.name + ".part")

            with temporary.open("wb") as output:
                while chunk := await content.read(1024 * 1024):
                    output.write(chunk)

            temporary.replace(destination)

        await cls.ingest(destination)

        return destination

    @classmethod
    async def scan(cls) -> None:
        if cls._folder is None or not cls._folder.is_dir():
            return

        from trailframe.services.pipelines.pipeline_service import PipelineService

        items = 0

        for path in sorted(cls._folder.rglob("*")):
            if not cls._is_image(path):
                continue

            canonical = cls.canonical(path)

            if canonical in cls._known_files:
                continue

            cls._known_files.add(canonical)

            if cls._creation_throttle != 0:
                while PipelineService.get_queue_size() > cls._creation_throttle:
                    await asyncio.sleep(1)

            try:
                await PipelineService.next(await cls.to_photo(path))
            except Exception as exception:  # noqa: BLE001
                cls._known_files.discard(canonical)
                cls._log(f"failed to queue {path.name}: {exception}", logging.ERROR)
                continue

            items += 1

        if items:
            cls._log(f"Found {items} new files")

    @classmethod
    async def _watch(cls) -> None:
        while cls._running:
            await asyncio.sleep(cls._interval)
            await cls.scan()

    @classmethod
    def _get_lock(cls) -> asyncio.Lock:
        if cls._lock is None:
            cls._lock = asyncio.Lock()

        return cls._lock

    @classmethod
    def _unique_path(cls, folder: Path, filename: str) -> Path:
        name = Path(filename).name or "photo"
        candidate = folder / name

        if not candidate.exists():
            return candidate

        stem = candidate.stem
        suffix = candidate.suffix
        index = 1

        while True:
            candidate = folder / f"{stem}_{index}{suffix}"

            if not candidate.exists():
                return candidate

            index += 1

    @classmethod
    def _is_image(cls, path: Path) -> bool:
        return path.is_file() and path.suffix.lower() in cls.IMAGE_EXTENSIONS


def _file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None
