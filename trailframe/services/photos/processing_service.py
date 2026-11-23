from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, ClassVar

from PIL import Image, ImageOps
from sqlalchemy import select

from trailframe.models.photo import Photo
from trailframe.services.core.configuration_service import Node
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.core.thread_pool_service import ThreadPoolService
from trailframe.services.photos.duplicates_service import DuplicatesService
from trailframe.services.photos.folder_service import FolderService
from trailframe.services.processors import ProcessingContext, Processor, create_processors
from trailframe.services.service import Service

_FORMAT_ALIASES = {"jpg": "jpeg", "tif": "tiff"}

MIN_TARGET_SIZE = 64
MAX_TARGET_SIZE = 8192
MAX_TARGETS = 5

# Analysis that depends on the pixels (not on the original file or its metadata).
_RESCAN_SCANNERS = ("Object", "PerceptualHash")


class ReprocessError(Exception):
    """A reprocess request that cannot be honoured."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class ProcessingService(Service):
    """Photo preprocessing: decoded originals are re-encoded into alternatives.

    The service is a technical driver only: it decodes the original, runs the
    configured processor chain, and writes the encoded files. The individual
    steps live in `trailframe.services.processors` and record their own
    provenance in `photo.processing`.

    The originals live in `photos_folder` and are owned by `FolderService`; this
    service reads them and writes the configured alternatives into the processed
    folder (WebP by default). The alternatives carry only pixels: EXIF stays a
    property of the original, and orientation is baked into the output.
    """

    _reconfig_safe = False
    _requires = ("ThreadPoolService", "FolderService", "PipelineService")

    _folder: Path | None = None
    _alternatives: ClassVar[list[int]] = []
    _main: int | None = None
    _format: ClassVar[str] = "webp"
    _quality = 90
    _processors: ClassVar[list[Processor]] = []
    _reprocessing: ClassVar[set[int]] = set()

    @classmethod
    def _configure(cls, config: Node) -> None:
        general_node = config.get_node("general", "General parameters")
        cls._folder = Path(
            general_node.get_path_value("processed_folder", "Folder where processed photos are stored", "processed")
        )
        cls._folder.mkdir(parents=True, exist_ok=True)

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

        cls._processors = create_processors(config)

    # --- processed storage -------------------------------------------------

    @classmethod
    def get_folder(cls) -> Path:
        """The processed folder, where alternatives are written."""
        if cls._folder is None:
            raise RuntimeError("ProcessingService is not configured")

        return cls._folder

    @classmethod
    def resolve(cls, stored: str | Path) -> Path:
        """Absolute location of an alternative stored relative to the processed folder."""
        path = Path(stored)

        if path.is_absolute() or cls._folder is None:
            return path

        return cls._folder / path

    @classmethod
    def delete_file(cls, path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError as exception:
            cls._log(f"failed to delete {path}: {exception}", logging.WARNING)

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
    def delete_alternatives(cls, photo: Photo) -> None:
        """Remove every processed file of a photo; the original is untouched."""
        for entry in photo.alternatives or []:
            stored = entry.get("path") if isinstance(entry, dict) else None

            if stored:
                cls.delete_file(cls.resolve(stored))

    # --- preprocessing ----------------------------------------------------

    @classmethod
    def needs_processing(cls, photo: Photo) -> bool:
        """Whether the photo is missing the output of an enabled processor.

        Run state is derived from the recorded `processing` steps, so photos
        processed by an earlier release (or before a processor existed) are
        picked up again on the next pipeline pass, like a scanner marker.
        """
        if photo.source == "Remote" or not cls._alternatives:
            return False

        if not photo.alternatives:
            return True

        steps = [step for step in (photo.processing or []) if isinstance(step, dict)]

        return any(not processor.ran(steps) for processor in cls._processors if processor.accept())

    @classmethod
    async def preprocess(cls, photo: Photo) -> bool:
        """Generate (or refresh) the alternatives of an original photo.

        Called by the `Processing` pipeline scanner after the metadata scanners
        and before the pixel consumers. Photos that already carry the output of
        every enabled processor are left alone.
        """
        if not cls.needs_processing(photo):
            return False

        original = FolderService.resolve(photo.path)

        if not original.is_file():
            cls._log(f"original not found for {photo.path}", logging.WARNING)
            return False

        targets, main_target = cls._targets_for(photo)
        entries, steps = await ThreadPoolService.run(cls._encode, original, targets, main_target)
        old_alternatives = list(photo.alternatives or [])
        old_target = photo.main().target_size

        photo.alternatives = entries
        photo.processing = steps

        if old_alternatives:
            cls._delete_superseded(old_alternatives, entries)
            cls._invalidate_thumbnails(photo, old_target)

        return True

    @classmethod
    def _targets_for(cls, photo: Photo) -> tuple[list[int], int | None]:
        """Targets to regenerate: the photo's own set, or the configured one."""
        entries = [
            entry
            for entry in (photo.alternatives or [])
            if isinstance(entry, dict) and entry.get("target_size") is not None
        ]

        if not entries:
            return list(cls._alternatives), cls._main

        targets = sorted({int(entry["target_size"]) for entry in entries})
        current_main = next((int(entry["target_size"]) for entry in entries if entry.get("main")), None)

        if current_main in targets:
            return targets, current_main

        return targets, cls._main if cls._main in targets else targets[-1]

    @classmethod
    def _delete_superseded(cls, old: list[dict], new: list[dict]) -> None:
        keep = {entry["path"] for entry in new if isinstance(entry, dict) and entry.get("path")}

        for entry in old:
            stored = entry.get("path") if isinstance(entry, dict) else None

            if stored and stored not in keep:
                cls.delete_file(cls.resolve(stored))

    @classmethod
    def _invalidate_thumbnails(cls, photo: Photo, old_target: int | None) -> None:
        """Drop the thumbnails of both the previous and the new main target."""
        from trailframe.services.photos.thumbnail_service import ThumbnailService

        ThumbnailService.delete_target(photo, old_target)
        ThumbnailService.delete_target(photo, photo.main().target_size)

    @classmethod
    async def reprocess(
        cls,
        photo_id: int,
        *,
        alternatives: list[int] | None = None,
        main_target: int | None = None,
        overrides: dict[str, Any] | None = None,
        rescan: bool = True,
    ) -> None:
        """Regenerate the alternatives of an existing photo.

        The original is never modified: the new files are written first, the row
        is swapped, and only then are the previous files and thumbnails removed.
        """
        if photo_id in cls._reprocessing:
            raise ReprocessError("This photo is already being reprocessed", 409)

        cls._reprocessing.add(photo_id)

        try:
            await cls._reprocess(
                photo_id, alternatives=alternatives, main_target=main_target, overrides=overrides, rescan=rescan
            )
        finally:
            cls._reprocessing.discard(photo_id)

    @classmethod
    async def _reprocess(
        cls,
        photo_id: int,
        *,
        alternatives: list[int] | None,
        main_target: int | None,
        overrides: dict[str, Any] | None,
        rescan: bool,
    ) -> None:
        photo = await cls._find_by_id(photo_id)

        if photo is None:
            raise ReprocessError(f"Photo {photo_id} not found", 404)

        if photo.source == "Remote":
            raise ReprocessError("Remote photos have no original to reprocess", 422)

        original = FolderService.resolve(photo.path)

        if not original.is_file():
            raise ReprocessError("The original file is not available", 422)

        targets, main_target = cls._resolve_targets(photo, alternatives, main_target)
        cls._validate_overrides(overrides)
        old_alternatives = list(photo.alternatives or [])
        old_target = photo.main().target_size

        entries, steps = await ThreadPoolService.run(cls._encode, original, targets, main_target, overrides)

        async def _save(session) -> None:
            stored = (await session.execute(select(Photo).where(Photo.id == photo_id))).scalar_one_or_none()

            if stored is None:
                raise ReprocessError(f"Photo {photo_id} not found", 404)

            stored.alternatives = entries
            stored.processing = steps

            if rescan:
                cls._reset_analysis(stored)

            await session.commit()

        try:
            await DatabaseService.execute(_save)
        except Exception:
            for entry in entries:
                cls.delete_file(cls.resolve(entry["path"]))

            raise

        new_paths = {entry["path"] for entry in entries}

        for entry in old_alternatives:
            stored_path = entry.get("path") if isinstance(entry, dict) else None

            if stored_path and stored_path not in new_paths:
                cls.delete_file(cls.resolve(stored_path))

        from trailframe.services.photos.thumbnail_service import ThumbnailService

        ThumbnailService.delete_target(photo, old_target)
        ThumbnailService.delete_target(photo, main_target)

        if rescan:
            from trailframe.services.pipelines.item import Item
            from trailframe.services.pipelines.pipeline_service import PipelineService

            updated = await cls._find_by_id(photo_id)

            if updated is not None:
                await PipelineService.next(Item(updated))

    @classmethod
    def _resolve_targets(
        cls, photo: Photo, alternatives: list[int] | None, main_target: int | None
    ) -> tuple[list[int], int]:
        entries = [entry for entry in (photo.alternatives or []) if isinstance(entry, dict)]
        current = [int(entry["target_size"]) for entry in entries if entry.get("target_size") is not None]

        if alternatives is not None and len(alternatives) == 0:
            raise ReprocessError("At least one target size is required")

        try:
            targets = sorted({int(size) for size in (alternatives if alternatives is not None else current)})
        except (TypeError, ValueError):
            raise ReprocessError("Target sizes must be integers") from None

        if not targets:
            targets = sorted({int(size) for size in cls._alternatives})

        if not targets:
            raise ReprocessError("No target size is configured")

        if len(targets) > MAX_TARGETS:
            raise ReprocessError(f"At most {MAX_TARGETS} target sizes are allowed")

        for size in targets:
            if not MIN_TARGET_SIZE <= size <= MAX_TARGET_SIZE:
                raise ReprocessError(f"Target sizes must be between {MIN_TARGET_SIZE} and {MAX_TARGET_SIZE} px")

        current_main = next(
            (
                int(entry["target_size"])
                for entry in entries
                if entry.get("main") and entry.get("target_size") is not None
            ),
            None,
        )

        if main_target is None:
            if current_main in targets:
                main_target = current_main
            elif cls._main in targets:
                main_target = cls._main
            else:
                main_target = targets[-1]
        elif main_target not in targets:
            raise ReprocessError("The main target must be one of the generated sizes")

        return targets, main_target

    @classmethod
    def _validate_overrides(cls, overrides: dict[str, Any] | None) -> None:
        for processor in cls._processors:
            problem = processor.validate_override((overrides or {}).get(processor.name))

            if problem:
                raise ReprocessError(problem)

    @classmethod
    def _reset_analysis(cls, photo: Photo) -> None:
        """Clear the pixel-derived analysis so the normal pipeline recomputes it."""
        photo.scanners = [name for name in (photo.scanners or []) if name not in _RESCAN_SCANNERS]
        photo.objects = {}
        photo.phash = None
        DuplicatesService.mark_deleted(photo.id)

    @classmethod
    async def _find_by_id(cls, photo_id: int) -> Photo | None:
        async def _lookup(session) -> Photo | None:
            return (await session.execute(select(Photo).where(Photo.id == photo_id))).scalar_one_or_none()

        return await DatabaseService.execute(_lookup)

    @classmethod
    def _encode(
        cls, original: Path, targets: list[int], main_target: int | None, overrides: dict[str, Any] | None = None
    ) -> tuple[list[dict], list[dict]]:
        """Run the processor chain and write the alternatives.

        The driver only decodes, chains the processors, encodes and stores the
        files. Runs on the shared thread pool; files written by a failed attempt
        are removed again, so a partial run never leaves unreferenced
        alternatives behind.
        """
        entries: list[dict] = []
        steps: list[dict] = []
        folder = cls.get_folder()
        fmt = _FORMAT_ALIASES.get(cls._format, cls._format)
        suffix = ".jpg" if fmt == "jpeg" else f".{fmt}"
        written: list[Path] = []

        try:
            with Image.open(original) as handle:
                base = ImageOps.exif_transpose(handle)
                base.load()

                context = ProcessingContext(
                    source_size=base.size, format=fmt, quality=cls._quality, overrides=dict(overrides or {})
                )
                chain = [processor for processor in cls._processors if processor.accept(context)]

                # A per-photo override that disables a processor must leave a
                # recipe marker, otherwise the next pipeline pass sees a missing
                # step and re-enables the configured correction.
                for processor in cls._processors:
                    override = (overrides or {}).get(processor.name)

                    if (
                        processor.overridable
                        and processor.accept()
                        and processor not in chain
                        and getattr(override, "enabled", None) is False
                    ):
                        steps.append(processor.skipped_step())

                for processor in chain:
                    processor.prepare(base, context)

                # Pre-downscale by the chain's own shrink ratio, so the border
                # crop trims the extra pixels instead of eating into the target.
                ratio = 1.0

                for processor in chain:
                    ratio *= processor.scale(context)

                for index, target in enumerate(targets):
                    context.target = target
                    image = base.copy()
                    requested = math.ceil(target / ratio) if ratio > 0 else target

                    if requested < max(image.size):
                        image.thumbnail((requested, requested), Image.Resampling.LANCZOS)

                    context.working_size = image.size

                    for processor in chain:
                        result = processor.execute(image, context)
                        image = result.image

                        if result.step is not None and (processor.per_target or index == 0):
                            steps.append(result.step)

                    if image.mode not in ("RGB", "RGBA"):
                        if image.mode in ("P", "PA") and "transparency" in image.info:
                            image = image.convert("RGBA")
                        else:
                            image = image.convert("RGB")

                    filename = f"{original.stem}_{target}{suffix}"
                    destination = cls._unique_path(folder, filename)
                    temporary = destination.with_name(destination.name + ".part")

                    image.save(temporary, format=fmt.upper(), quality=cls._quality)
                    width, height = image.size
                    image.close()
                    written.extend((temporary, destination))
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
        except Exception:
            for path in written:
                path.unlink(missing_ok=True)

            raise

        order = {processor.step: index for index, processor in enumerate(cls._processors)}
        steps.sort(key=lambda step: order.get(step.get("step"), len(order)))

        return entries, steps
