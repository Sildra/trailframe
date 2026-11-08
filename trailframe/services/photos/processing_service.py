from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import ClassVar

from trailframe.services.core.configuration_service import Node
from trailframe.services.core.thread_pool_service import ThreadPoolService
from trailframe.services.photos.folder_service import FolderService
from trailframe.services.service import Service


class ProcessingService(Service):
    """Stage uploads in an originals folder before adding them to the library.

    Uploaded files are written to `originals_folder` first. Processing is
    intentionally minimal for now: each original is copied as-is into the photos
    folder and handed to the pipeline. The original is kept, so the folder also
    acts as an archive of what was uploaded.
    """

    _reconfig_safe = False
    _requires = ("ThreadPoolService", "FolderService")
    _interval = 10

    _originals_folder: Path | None = None
    _failsafe = False
    _task: asyncio.Task | None = None
    _running = False
    _lock: ClassVar[asyncio.Lock | None] = None

    @classmethod
    def _configure(cls, config: Node) -> None:
        general_node = config.get_node("general", "General parameters")
        cls._originals_folder = Path(
            general_node.get_path_value(
                "originals_folder", "Folder where uploaded originals are staged before processing", "originals"
            )
        )
        cls._originals_folder.mkdir(parents=True, exist_ok=True)
        cls._failsafe = general_node.get_path_value(
            "failsafe", "Start without scanning or watching the originals folder", False
        )

    @classmethod
    async def _start(cls) -> None:
        if cls._originals_folder is None:
            raise RuntimeError("ProcessingService is not configured")

        if cls._failsafe:
            cls._log("failsafe: skipping originals scan and watch")
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
    async def upload(cls, filename: str, content) -> Path:
        """Store an upload in the originals folder, then process it."""
        if cls._originals_folder is None:
            raise RuntimeError("ProcessingService is not configured")

        async with cls._get_lock():
            destination = cls._unique_path(cls._originals_folder, Path(filename or "photo").name)
            temporary = destination.with_name(destination.name + ".part")

            with temporary.open("wb") as output:
                while chunk := await content.read(1024 * 1024):
                    output.write(chunk)

            temporary.replace(destination)

        return await cls.process(destination)

    @classmethod
    async def process(cls, original: Path) -> Path:
        """Copy one original into the photos folder and queue it for scanning.

        Processing is a bare copy for now. The exact target is reused when it
        already exists, so a leftover original is not imported twice.
        """
        lock = cls._get_lock()

        async with lock:
            target = FolderService.get_folder() / original.name

            if target.exists():
                return target

            destination = cls._unique_path(FolderService.get_folder(), original.name)
            temporary = destination.with_name(destination.name + ".part")

            await ThreadPoolService.run(shutil.copy2, original, temporary)
            temporary.replace(destination)

        await FolderService.ingest(destination)

        return destination

    @classmethod
    async def scan(cls) -> None:
        if cls._originals_folder is None or not cls._originals_folder.is_dir():
            return

        processed = 0

        for path in sorted(cls._originals_folder.iterdir()):
            if not FolderService._is_image(path):
                continue

            if (FolderService.get_folder() / path.name).exists():
                continue

            await cls.process(path)
            processed += 1

        if processed:
            cls._log(f"Processed {processed} original(s)")

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
    async def _watch(cls) -> None:
        while cls._running:
            await cls.scan()
            await asyncio.sleep(cls._interval)
