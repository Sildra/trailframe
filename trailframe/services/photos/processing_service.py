from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from PIL import Image, ImageOps
from PIL import __version__ as pillow_version
from sqlalchemy import select

from trailframe.models.photo import Photo
from trailframe.services.core.configuration_service import Node
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.core.thread_pool_service import ThreadPoolService
from trailframe.services.photos.folder_service import FolderService
from trailframe.services.service import Service

_FORMAT_ALIASES = {"jpg": "jpeg", "tif": "tiff"}


class ProcessingService(Service):
    """Original storage and preprocessing.

    Uploaded files are stored in `originals_folder` and kept as the archive. Each
    original is decoded once and re-encoded into the configured alternatives in
    the processed folder (WebP by default), then handed to the pipeline. The
    alternatives carry only pixels: EXIF stays a property of the original, and
    orientation is baked into the output.
    """

    SOURCE: ClassVar[str] = "File"

    _reconfig_safe = False
    _requires = ("ThreadPoolService", "FolderService", "PipelineService")
    _interval = 10

    _originals_folder: Path | None = None
    _trash_folder: Path | None = None
    _alternatives: ClassVar[list[int]] = []
    _main: int | None = None
    _format: ClassVar[str] = "webp"
    _quality = 90
    _failsafe = False
    _task: asyncio.Task | None = None
    _running = False
    _lock: ClassVar[asyncio.Lock | None] = None
    _seen: ClassVar[set[str]] = set()

    @classmethod
    def _configure(cls, config: Node) -> None:
        general_node = config.get_node("general", "General parameters")
        cls._originals_folder = Path(
            general_node.get_path_value("originals_folder", "Folder where uploaded originals are stored", "originals")
        )
        cls._originals_folder.mkdir(parents=True, exist_ok=True)
        cls._trash_folder = Path(
            general_node.get_path_value("trash_folder", "Folder where deleted photos are moved", "trash")
        )
        cls._trash_folder.mkdir(parents=True, exist_ok=True)
        cls._failsafe = general_node.get_path_value(
            "failsafe", "Start without scanning or watching the originals folder", False
        )

        processing_node = config.get_node("processing", "Photo preprocessing")
        alternatives = processing_node.get_path_value(
            "alternatives", "Target sizes (longest edge, px) generated for each original", [1080]
        )
        cls._alternatives = sorted({int(size) for size in alternatives})
        cls._main = int(processing_node.get_path_value("main", "Target size used by pipelines and the gallery", 1080))
        configured_format = str(
            processing_node.get_path_value("format", "Output format for alternatives", "webp")
        ).lower()
        cls._format = _FORMAT_ALIASES.get(configured_format, configured_format)
        cls._quality = int(processing_node.get_path_value("quality", "Encoder quality for alternatives", 90))

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

    # --- original storage -------------------------------------------------

    @classmethod
    def get_originals_folder(cls) -> Path:
        if cls._originals_folder is None:
            raise RuntimeError("ProcessingService is not configured")

        return cls._originals_folder

    @classmethod
    def resolve(cls, stored: str | Path) -> Path:
        """Absolute location of an original stored relative to the originals folder."""
        path = Path(stored)

        if path.is_absolute() or cls._originals_folder is None:
            return path

        return cls._originals_folder / path

    @classmethod
    def canonical(cls, path: str | Path) -> str:
        """Storage form of an original: posix, relative to the originals folder."""
        p = Path(path)

        if cls._originals_folder is None:
            return p.as_posix()

        try:
            return p.resolve().relative_to(cls._originals_folder.resolve()).as_posix()
        except ValueError:
            return p.as_posix()

    @classmethod
    def delete(cls, path: Path) -> None:
        """Move an original to the trash folder."""
        if not path.is_file() or cls._trash_folder is None:
            return

        destination = cls._trash_folder / path.name

        if destination.exists():
            destination = cls._trash_folder / f"{path.stem}_{path.stat().st_size}{path.suffix}"

        shutil.move(str(path), str(destination))

    # --- upload and processing -------------------------------------------

    @classmethod
    async def upload(cls, filename: str, content) -> Photo:
        """Store an upload in the originals folder, then preprocess it."""
        if cls._originals_folder is None:
            raise RuntimeError("ProcessingService is not configured")

        async with cls._get_lock():
            destination = cls._unique_path(cls._originals_folder, Path(filename or "photo").name)
            temporary = destination.with_name(destination.name + ".part")

            with temporary.open("wb") as output:
                while chunk := await content.read(1024 * 1024):
                    output.write(chunk)

            temporary.replace(destination)

        photo = await cls.process(destination)

        if photo is None:
            photo = await cls._find(cls.canonical(destination))

        if photo is None:
            raise RuntimeError(f"Failed to process original {destination}")

        return photo

    @classmethod
    async def process(cls, original: Path) -> Photo | None:
        """Preprocess one original and queue it for scanning.

        Returns None when the original is already known, so a leftover original is
        not imported twice.
        """
        canonical = cls.canonical(original)
        cls._seen.add(canonical)

        if await cls._find(canonical) is not None:
            return None

        photo = Photo(path=canonical, filename=original.name, file_size=_file_size(original), source=cls.SOURCE)

        try:
            photo.alternatives, photo.processing = await cls._generate(original, canonical)
        except Exception:
            cls._seen.discard(canonical)
            raise

        from trailframe.services.pipelines.pipeline_service import PipelineService

        await PipelineService.next(photo)

        return photo

    @classmethod
    async def _generate(cls, original: Path, source_path: str) -> tuple[list[dict], list[dict]]:
        if not cls._alternatives:
            return [], []

        return await ThreadPoolService.run(
            cls._encode, original, source_path, list(cls._alternatives), cls._main, cls._format, cls._quality
        )

    @classmethod
    def _encode(
        cls,
        original: Path,
        source_path: str,
        targets: list[int],
        main_target: int | None,
        output_format: str,
        quality: int,
    ) -> tuple[list[dict], list[dict]]:
        """Encode the configured alternatives. Runs on the shared thread pool."""
        entries: list[dict] = []
        steps: list[dict] = []
        folder = FolderService.get_folder()
        fmt = _FORMAT_ALIASES.get(output_format, output_format)
        suffix = ".jpg" if fmt == "jpeg" else f".{fmt}"
        at = datetime.now(UTC).isoformat()

        with Image.open(original) as handle:
            base = ImageOps.exif_transpose(handle)
            base.load()
            longest = max(base.size)

            for target in targets:
                image = base.copy()

                if target < longest:
                    image.thumbnail((target, target), Image.Resampling.LANCZOS)

                if image.mode not in ("RGB", "RGBA"):
                    if image.mode in ("P", "PA") and "transparency" in image.info:
                        image = image.convert("RGBA")
                    else:
                        image = image.convert("RGB")

                filename = f"{original.stem}_{target}{suffix}"
                destination = cls._unique_path(folder, filename)
                temporary = destination.with_name(destination.name + ".part")

                image.save(temporary, format=fmt.upper(), quality=quality)
                width, height = image.size
                image.close()
                temporary.replace(destination)

                entries.append(
                    {
                        "target_size": target,
                        "path": destination.relative_to(folder).as_posix(),
                        "filename": destination.name,
                        "file_size": destination.stat().st_size,
                        "width": width,
                        "height": height,
                        "main": main_target is not None and target == main_target,
                    }
                )
                steps.append(
                    {
                        "step": "downscale" if target < longest else "transcode",
                        "source": source_path,
                        "target_size": target,
                        "format": fmt,
                        "quality": quality,
                        "tool": "Pillow",
                        "tool_version": pillow_version,
                        "at": at,
                    }
                )

        return entries, steps

    @classmethod
    async def _find(cls, canonical: str) -> Photo | None:
        async def _lookup(session) -> Photo | None:
            result = await session.execute(select(Photo).where(Photo.path == canonical))
            return result.scalar_one_or_none()

        return await DatabaseService.execute(_lookup)

    # --- scanning ---------------------------------------------------------

    @classmethod
    async def scan(cls) -> None:
        if cls._originals_folder is None or not cls._originals_folder.is_dir():
            return

        processed = 0

        for path in sorted(cls._originals_folder.iterdir()):
            if not FolderService._is_image(path):
                continue

            canonical = cls.canonical(path)

            if canonical in cls._seen:
                continue

            try:
                if await cls.process(path) is not None:
                    processed += 1
            except Exception as exception:  # noqa: BLE001
                cls._seen.discard(canonical)
                cls._log(f"failed to process {path.name}: {exception}", logging.ERROR)

        if processed:
            cls._log(f"Processed {processed} original(s)")

    @classmethod
    async def _watch(cls) -> None:
        while cls._running:
            await cls.scan()
            await asyncio.sleep(cls._interval)

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


def _file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None
