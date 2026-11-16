from __future__ import annotations

import asyncio
import logging
import math
import shutil
from dataclasses import replace
from pathlib import Path
from typing import ClassVar

from PIL import Image, ImageOps
from sqlalchemy import select

from trailframe.models.photo import Photo
from trailframe.services.core.configuration_service import Node
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.core.thread_pool_service import ThreadPoolService
from trailframe.services.photos.duplicates_service import DuplicatesService
from trailframe.services.photos.folder_service import FolderService
from trailframe.services.photos.processing.tilt import (
    CROP_MODE_MAXIMUM_RECTANGLE,
    CROP_MODE_NONE,
    MANUAL_METHOD,
    TiltDecision,
    TiltEstimate,
    TiltOverride,
    TiltSettings,
    correct,
    decide,
    detect_tilt,
    get_detector,
)
from trailframe.services.service import Service

_FORMAT_ALIASES = {"jpg": "jpeg", "tif": "tiff"}

MIN_TARGET_SIZE = 64
MAX_TARGET_SIZE = 8192
MAX_TARGETS = 5
MAX_MANUAL_ANGLE = 45.0

# Analysis that depends on the pixels (not on the original file or its metadata).
_RESCAN_SCANNERS = ("Object", "PerceptualHash")

_CROP_MODES = {CROP_MODE_MAXIMUM_RECTANGLE, CROP_MODE_NONE}


class ReprocessError(Exception):
    """A reprocess request that cannot be honoured."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


_REASON_TEXT = {
    "no_estimate": "no estimate",
    "below_min_angle": "below minimum angle",
    "above_max_angle": "above maximum angle",
    "low_confidence": "low confidence",
    "auto_apply_disabled": "auto-apply disabled",
    "disabled": "disabled",
    "failed": "failed",
}


class ProcessingService(Service):
    """Original storage and preprocessing.

    Uploaded files are stored in `photos_folder` and kept as the archive. Each
    original is decoded once and re-encoded into the configured alternatives in
    the processed folder (WebP by default), then handed to the pipeline. The
    alternatives carry only pixels: EXIF stays a property of the original, and
    orientation is baked into the output.
    """

    SOURCE: ClassVar[str] = "File"

    _reconfig_safe = False
    _requires = ("ThreadPoolService", "FolderService", "PipelineService")
    _interval = 10

    _photos_folder: Path | None = None
    _trash_folder: Path | None = None
    _alternatives: ClassVar[list[int]] = []
    _main: int | None = None
    _format: ClassVar[str] = "webp"
    _quality = 90
    _tilt: ClassVar[TiltSettings] = TiltSettings()
    _failsafe = False
    _task: asyncio.Task | None = None
    _running = False
    _lock: ClassVar[asyncio.Lock | None] = None
    _seen: ClassVar[set[str]] = set()
    _reprocessing: ClassVar[set[int]] = set()

    @classmethod
    def _configure(cls, config: Node) -> None:
        general_node = config.get_node("general", "General parameters")
        cls._photos_folder = Path(
            general_node.get_path_value("photos_folder", "Folder where uploaded photos are stored", "photos")
        )
        cls._photos_folder.mkdir(parents=True, exist_ok=True)
        cls._trash_folder = Path(
            general_node.get_path_value("trash_folder", "Folder where deleted photos are moved", "trash")
        )
        cls._trash_folder.mkdir(parents=True, exist_ok=True)
        cls._failsafe = general_node.get_path_value(
            "failsafe", "Start without scanning or watching the photos folder", False
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

        tilt_node = processing_node.get_node("tilt", "Automatic horizon straightening")
        cls._tilt = TiltSettings.from_node(tilt_node)

        if cls._tilt.enabled and get_detector(cls._tilt.method) is None:
            cls._log(f"unknown tilt detector '{cls._tilt.method}', horizon correction is disabled", logging.WARNING)

    @classmethod
    async def _start(cls) -> None:
        if cls._photos_folder is None:
            raise RuntimeError("ProcessingService is not configured")

        if cls._failsafe:
            cls._log("failsafe: skipping photos scan and watch")
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
    def get_photos_folder(cls) -> Path:
        if cls._photos_folder is None:
            raise RuntimeError("ProcessingService is not configured")

        return cls._photos_folder

    @classmethod
    def resolve(cls, stored: str | Path) -> Path:
        """Absolute location of an original stored relative to the photos folder."""
        path = Path(stored)

        if path.is_absolute() or cls._photos_folder is None:
            return path

        return cls._photos_folder / path

    @classmethod
    def canonical(cls, path: str | Path) -> str:
        """Storage form of an original: posix, relative to the photos folder."""
        p = Path(path)

        if cls._photos_folder is None:
            return p.as_posix()

        try:
            return p.resolve().relative_to(cls._photos_folder.resolve()).as_posix()
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
        """Store an upload in the photos folder, then preprocess it."""
        if cls._photos_folder is None:
            raise RuntimeError("ProcessingService is not configured")

        async with cls._get_lock():
            destination = cls._unique_path(cls._photos_folder, Path(filename or "photo").name)
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
            photo.alternatives, photo.processing = await cls._generate(original)
        except Exception:
            cls._seen.discard(canonical)
            raise

        from trailframe.services.pipelines.pipeline_service import PipelineService

        await PipelineService.next(photo)

        return photo

    @classmethod
    async def reprocess(
        cls,
        photo_id: int,
        *,
        alternatives: list[int] | None = None,
        main_target: int | None = None,
        tilt: TiltOverride | None = None,
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
            await cls._reprocess(photo_id, alternatives=alternatives, main_target=main_target, tilt=tilt, rescan=rescan)
        finally:
            cls._reprocessing.discard(photo_id)

    @classmethod
    async def _reprocess(
        cls,
        photo_id: int,
        *,
        alternatives: list[int] | None,
        main_target: int | None,
        tilt: TiltOverride | None,
        rescan: bool,
    ) -> None:
        photo = await cls._find_by_id(photo_id)

        if photo is None:
            raise ReprocessError(f"Photo {photo_id} not found", 404)

        if photo.source == "Remote":
            raise ReprocessError("Remote photos have no original to reprocess", 422)

        original = cls.resolve(photo.path)

        if not original.is_file():
            raise ReprocessError("The original file is not available", 422)

        targets, main_target = cls._resolve_targets(photo, alternatives, main_target)
        tilt = cls._validate_tilt(tilt)
        old_alternatives = list(photo.alternatives or [])
        old_target = photo.main().target_size

        entries, steps = await ThreadPoolService.run(
            cls._encode, original, targets, main_target, cls._format, cls._quality, cls._tilt, tilt
        )

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
                FolderService.delete_file(FolderService.resolve(entry["path"]))

            raise

        new_paths = {entry["path"] for entry in entries}

        for entry in old_alternatives:
            stored_path = entry.get("path") if isinstance(entry, dict) else None

            if stored_path and stored_path not in new_paths:
                FolderService.delete_file(FolderService.resolve(stored_path))

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
    def _validate_tilt(cls, tilt: TiltOverride | None) -> TiltOverride | None:
        if tilt is None:
            return None

        if tilt.angle is not None and (not math.isfinite(tilt.angle) or abs(tilt.angle) > MAX_MANUAL_ANGLE):
            raise ReprocessError(f"The manual angle must be within ±{MAX_MANUAL_ANGLE:g}°")

        if tilt.crop_mode is not None and tilt.crop_mode not in _CROP_MODES:
            raise ReprocessError(f"Unknown crop mode '{tilt.crop_mode}'")

        return tilt

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
    async def _generate(cls, original: Path) -> tuple[list[dict], list[dict]]:
        if not cls._alternatives:
            return [], []

        return await ThreadPoolService.run(
            cls._encode, original, list(cls._alternatives), cls._main, cls._format, cls._quality, cls._tilt
        )

    @classmethod
    def _encode(
        cls,
        original: Path,
        targets: list[int],
        main_target: int | None,
        output_format: str,
        quality: int,
        tilt: TiltSettings,
        override: TiltOverride | None = None,
    ) -> tuple[list[dict], list[dict]]:
        """Encode the alternatives. Runs on the shared thread pool.

        Files written by a failed attempt are removed again, so a partial run
        never leaves unreferenced alternatives behind.
        """
        entries: list[dict] = []
        steps: list[dict] = []
        folder = FolderService.get_folder()
        fmt = _FORMAT_ALIASES.get(output_format, output_format)
        suffix = ".jpg" if fmt == "jpeg" else f".{fmt}"
        settings = tilt

        if override is not None and override.crop_mode is not None:
            settings = replace(tilt, crop_mode=override.crop_mode)

        written: list[Path] = []

        try:
            with Image.open(original) as handle:
                base = ImageOps.exif_transpose(handle)
                base.load()

                decision = cls._tilt_decision(base, settings, override)

                record = cls._tilt_record(decision, settings)

                if record is not None:
                    steps.append(record)

                longest = max(base.size)

                for target in targets:
                    image = base.copy()

                    if target < longest:
                        image.thumbnail((target, target), Image.Resampling.LANCZOS)

                    if decision.applied and decision.estimate is not None:
                        image, _ = correct(image, decision.estimate.angle, settings)

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
                    steps.append(
                        {
                            "step": "downscale" if target < longest else "transcode",
                            "summary": f"{width} × {height}",
                            "details": {"Target size": f"{target} px", "Format": fmt.upper(), "Quality": str(quality)},
                            "meta": {},
                        }
                    )
        except Exception:
            for path in written:
                path.unlink(missing_ok=True)

            raise

        return entries, steps

    @classmethod
    def _tilt_decision(
        cls, image: Image.Image, tilt: TiltSettings, override: TiltOverride | None = None
    ) -> TiltDecision:
        if override is not None:
            if override.angle is not None:
                estimate = TiltEstimate(angle=override.angle, confidence=1.0, method=MANUAL_METHOD)

                return TiltDecision(estimate, True, "manual")

            if override.enabled is False:
                return TiltDecision(None, False, "disabled")

        if not tilt.enabled:
            return TiltDecision(None, False, "disabled")

        try:
            estimate = detect_tilt(image, tilt)
        except Exception as exception:  # noqa: BLE001
            cls._log(f"tilt detection failed: {exception}", logging.WARNING)
            return TiltDecision(None, False, "failed")

        return decide(estimate, tilt)

    @classmethod
    def _tilt_record(cls, decision: TiltDecision, settings: TiltSettings) -> dict | None:
        estimate = decision.estimate

        if estimate is None:
            return None

        details: dict[str, str] = {
            "Detection method": estimate.method,
            "Confidence": f"{estimate.confidence:.0%}",
            "Applied": "Yes" if decision.applied else "No",
        }
        meta: dict = {"crop_mode": settings.crop_mode}
        reference = estimate.reference_point

        if not decision.applied:
            details["Reason"] = _reason_text(decision.reason)

        if reference is not None:
            details["Reference point"] = f"{reference[0]:.1%}, {reference[1]:.1%}"
            meta["reference_point"] = {"x": round(reference[0], 4), "y": round(reference[1], 4)}

        if estimate.line is not None:
            meta["line"] = {
                "x1": round(estimate.line[0], 4),
                "y1": round(estimate.line[1], 4),
                "x2": round(estimate.line[2], 4),
                "y2": round(estimate.line[3], 4),
            }

        return {"step": "tilt", "summary": _format_angle(estimate.angle), "details": details, "meta": meta}

    @classmethod
    async def _find(cls, canonical: str) -> Photo | None:
        async def _lookup(session) -> Photo | None:
            result = await session.execute(select(Photo).where(Photo.path == canonical))
            return result.scalar_one_or_none()

        return await DatabaseService.execute(_lookup)

    # --- scanning ---------------------------------------------------------

    @classmethod
    async def scan(cls) -> None:
        if cls._photos_folder is None or not cls._photos_folder.is_dir():
            return

        processed = 0

        for path in sorted(cls._photos_folder.iterdir()):
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


def _reason_text(reason: str) -> str:
    return _REASON_TEXT.get(reason, reason.replace("_", " "))


def _format_angle(angle: float) -> str:
    rounded = round(float(angle), 2)

    if rounded == 0:
        rounded = 0.0

    return f"{rounded:+.2f}°"


def _file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None
