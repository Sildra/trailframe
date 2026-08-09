import asyncio
import shutil
from pathlib import Path

from gallery.models.photo import Photo
from gallery.services.configuration_service import Node
from gallery.services.pipeline_service import PipelineService
from gallery.services.service import Service


class FolderService(Service):
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".bmp"}

    _folder: Path | None = None
    _trash_folder: Path | None = None
    _interval = 60
    _known_files: set[Path] = set()
    _task: asyncio.Task | None = None
    _running = False

    @classmethod
    def _configure(cls, config: Node) -> None:
        cls._folder = Path(config.get_path_value("photos_folder", "Folder where photos are stored", "photos"))
        cls._folder.mkdir(parents=True, exist_ok=True)
        cls._trash_folder = Path(
            config.get_path_value("trash_folder", "Folder where deleted photos are moved", "trash")
        )
        cls._trash_folder.mkdir(parents=True, exist_ok=True)

    @classmethod
    async def _start(cls) -> None:
        if cls._folder is None:
            raise RuntimeError("FolderService is not configured")

        cls._running = True

        await cls.scan()

        cls._task = asyncio.create_task(cls._watch())

    @classmethod
    async def _stop(cls) -> None:
        cls._running = False

        if cls._task:
            cls._task.cancel()
            cls._task = None

    @classmethod
    async def scan(cls) -> None:
        for path in cls._folder.rglob("*"):
            if not cls._is_image(path):
                continue

            if path in cls._known_files:
                continue

            cls._known_files.add(path)

            await PipelineService.next(path)

    @classmethod
    async def upload(cls, filename: str, content) -> Path:
        destination = cls._folder / filename

        cls._known_files.add(destination)

        with destination.open("wb") as output:
            while chunk := await content.read(1024 * 1024):
                output.write(chunk)

        await PipelineService.next(destination)

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
