import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import ClassVar

import numpy as np
from PIL import Image, ImageOps
from sqlalchemy import select

from trailframe.models.photo import Photo, PhotoDetail
from trailframe.models.similarity import Fingerprint, FingerprintMarker, ImageSize, SimilarPhoto
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.core.thread_pool_service import ThreadPoolService
from trailframe.services.photos.photo_service import PhotoService
from trailframe.services.photos.thumbnail_service import ThumbnailService
from trailframe.services.service import Service

TEXTURE_GRID = 4
TEXTURE_SAMPLE = 64
TEXTURE_DISTANCE = 0.35
TEXTURE_CELL_DISTANCE = 0.18


@dataclass(frozen=True)
class _Texture:
    """A small colour/edge grid used when a photo has no YOLO detections."""

    cells: np.ndarray
    markers: list[FingerprintMarker]
    reference: ImageSize


class SimilarityError(Exception):
    """A user-correctable problem with a similarity request."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def _detection_signature(label: str, box: object, surface: object) -> str:
    """Coarse label/shape key that survives different image and crop sizes."""

    aspect_bucket = None
    size_bucket = None

    if isinstance(box, (list, tuple)) and len(box) >= 4:
        try:
            width = abs(float(box[2]) - float(box[0]))
            height = abs(float(box[3]) - float(box[1]))
        except (TypeError, ValueError):
            width = height = 0.0

        if width > 0 and height > 0:
            aspect_bucket = max(-4, min(4, round(math.log2(width / height) * 2)))

    if isinstance(surface, (int, float)) and not isinstance(surface, bool):
        size_bucket = max(0, min(10, round(float(surface) * 10)))

    return f"{label}|{aspect_bucket}|{size_bucket}"


def _object_sets(photo: Photo) -> tuple[set[str], set[str]]:
    """Return object labels and coarse label/shape signatures."""

    data = photo.objects if isinstance(photo.objects, dict) else {}
    detections = data.get("detections", [])
    labels: set[str] = set()
    signatures: set[str] = set()

    for detection in detections if isinstance(detections, list) else []:
        if not isinstance(detection, dict):
            continue

        label = str(detection.get("label") or "").strip().lower()

        if not label:
            continue

        labels.add(label)
        signatures.add(_detection_signature(label, detection.get("box"), detection.get("surface")))

    return labels, signatures


def _object_fingerprint(photo: Photo) -> Fingerprint | None:
    """Turn stored YOLO detections into normalised, shareable markers."""

    data = photo.objects if isinstance(photo.objects, dict) else {}
    detections = data.get("detections", [])
    reference = data.get("reference") if isinstance(data.get("reference"), dict) else {}
    width = int(reference.get("width") or 0)
    height = int(reference.get("height") or 0)

    if width <= 0 or height <= 0 or not isinstance(detections, list):
        return None

    markers: list[FingerprintMarker] = []

    for detection in detections:
        if not isinstance(detection, dict):
            continue

        label = str(detection.get("label") or "").strip().lower()
        box = detection.get("box")

        if not label or not isinstance(box, (list, tuple)) or len(box) != 4:
            continue

        try:
            x1, y1, x2, y2 = (float(value) for value in box)
        except (TypeError, ValueError):
            continue

        try:
            confidence = float(detection.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0

        markers.append(
            FingerprintMarker(
                key=_detection_signature(label, box, detection.get("surface")),
                label=label,
                kind="object",
                box=[
                    min(1.0, max(0.0, x1 / width)),
                    min(1.0, max(0.0, y1 / height)),
                    min(1.0, max(0.0, x2 / width)),
                    min(1.0, max(0.0, y2 / height)),
                ],
                confidence=min(1.0, max(0.0, confidence)),
            )
        )

    if not markers:
        return None

    return Fingerprint(method="objects", reference=ImageSize(width=width, height=height), markers=markers)


def _texture_fingerprint(photo: Photo) -> _Texture | None:
    """Measure a tiny colour/edge grid from the smallest available image."""

    path = ThumbnailService.get_thumbnail_path(photo)

    if not path.exists():
        path = PhotoService.resolve(photo)

    try:
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            width, height = image.size
            image = image.resize((TEXTURE_SAMPLE, TEXTURE_SAMPLE))
    except (OSError, ValueError):
        return None

    pixels = np.asarray(image, dtype=np.float32) / 255.0
    gray = pixels.mean(axis=2)
    gradient_x = np.diff(gray, axis=1)
    gradient_y = np.diff(gray, axis=0)
    horizontal = np.abs(gradient_x).mean(axis=1)
    vertical = np.abs(gradient_y).mean(axis=0)
    step = TEXTURE_SAMPLE // TEXTURE_GRID
    colors: list[np.ndarray] = []
    edges: list[float] = []
    directions: list[tuple[float, float]] = []
    markers: list[FingerprintMarker] = []

    for row in range(TEXTURE_GRID):
        rows = slice(row * step, (row + 1) * step)

        for column in range(TEXTURE_GRID):
            columns = slice(column * step, (column + 1) * step)
            colors.append(pixels[rows, columns].mean(axis=(0, 1)))
            edge = min(1.0, (float(horizontal[rows].mean()) + float(vertical[columns].mean())) / 2 * 8)
            directions.append(
                (
                    float(np.clip(gradient_x[rows, columns].mean() * 80, -1, 1)),
                    float(np.clip(gradient_y[rows, columns].mean() * 80, -1, 1)),
                )
            )
            markers.append(
                FingerprintMarker(
                    key=f"cell-{row}-{column}",
                    label="texture",
                    kind="texture",
                    box=[
                        column / TEXTURE_GRID,
                        row / TEXTURE_GRID,
                        (column + 1) / TEXTURE_GRID,
                        (row + 1) / TEXTURE_GRID,
                    ],
                    confidence=edge,
                )
            )
            edges.append(edge)

    centered = np.asarray(colors, dtype=np.float32)
    centered = centered - centered.mean(axis=0, keepdims=True) + 0.5
    cells = np.column_stack(
        (centered, np.asarray(edges, dtype=np.float32), np.asarray(directions, dtype=np.float32))
    )
    return _Texture(cells=cells, markers=markers, reference=ImageSize(width=width, height=height))


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _texture_match(left: _Texture, right: _Texture) -> tuple[float, set[str]]:
    """Return the overall score and the cells that match the reference."""

    delta = np.abs(left.cells - right.cells)
    distances = (
        0.5 * delta[:, :3].mean(axis=1)
        + 0.12 * delta[:, 3]
        + 0.19 * delta[:, 4]
        + 0.19 * delta[:, 5]
    )
    score = max(0.0, 1.0 - min(1.0, float(distances.mean()) / TEXTURE_DISTANCE))
    keys = {
        marker.key
        for marker, distance in zip(right.markers, distances, strict=True)
        if float(distance) <= TEXTURE_CELL_DISTANCE
    }
    return score, keys


def _with_shared(fingerprint: Fingerprint, keys: set[str]) -> Fingerprint:
    return fingerprint.model_copy(
        update={"markers": [marker.model_copy(update={"shared": marker.key in keys}) for marker in fingerprint.markers]}
    )


def _shared_count(fingerprint: Fingerprint | None) -> int:
    return sum(1 for marker in fingerprint.markers if marker.shared) if fingerprint else 0


class SimilarityService(Service):
    """Finds photos related to a seed by time, stored objects and texture."""

    _requires: ClassVar[tuple[str, ...]] = ("DatabaseService", "PhotoService", "ThreadPoolService", "ThumbnailService")

    @classmethod
    async def candidates(cls, photo_id: int, window_seconds: int, min_object_overlap: float) -> list[SimilarPhoto]:
        async def _fetch() -> tuple[Photo | None, list[Photo]]:
            async def _seed(session):
                return (await session.execute(select(Photo).where(Photo.id == photo_id))).scalar_one_or_none()

            seed = await DatabaseService.execute(_seed)

            if seed is None:
                raise SimilarityError(404, f"Photo {photo_id} not found")

            if seed.date is None:
                raise SimilarityError(422, "The seed photo has no capture date")

            start = seed.date - timedelta(seconds=window_seconds)
            end = seed.date + timedelta(seconds=window_seconds)

            async def _nearby(session):
                result = await session.execute(
                    select(Photo).where(Photo.date >= start, Photo.date <= end).order_by(Photo.date, Photo.id)
                )
                return list(result.scalars().all())

            return seed, await DatabaseService.execute(_nearby)

        try:
            seed, photos = await _fetch()
        except SimilarityError:
            raise
        except Exception as error:
            cls._log(f"similarity search failed: {error}", logging.ERROR)
            raise SimilarityError(500, "Similarity search failed") from error

        seed_labels, seed_signatures = _object_sets(seed)
        seed_objects = _object_fingerprint(seed)
        seed_texture = await ThreadPoolService.run(_texture_fingerprint, seed)
        results: list[tuple[SimilarPhoto, datetime | None]] = []

        for photo in photos:
            labels, signatures = _object_sets(photo)
            candidate_objects = _object_fingerprint(photo)
            best_score = 0.0
            fingerprint: Fingerprint | None = None

            if seed_objects and candidate_objects:
                signature_score = _jaccard(seed_signatures, signatures)
                label_score = _jaccard(seed_labels, labels)
                best_score = 0.6 * signature_score + 0.4 * label_score if seed_signatures else label_score
                fingerprint = _with_shared(candidate_objects, seed_signatures | seed_labels)
            elif seed_texture:
                candidate_texture = await ThreadPoolService.run(_texture_fingerprint, photo)

                if candidate_texture:
                    best_score, shared_cells = _texture_match(seed_texture, candidate_texture)
                    fingerprint = _with_shared(
                        Fingerprint(
                            method="texture", reference=candidate_texture.reference, markers=candidate_texture.markers
                        ),
                        shared_cells,
                    )

            shared = _shared_count(fingerprint)
            results.append(
                (
                    SimilarPhoto(
                        photo=PhotoDetail.from_photo(photo),
                        similar=best_score >= min_object_overlap and shared > 0,
                        score=round(best_score, 4),
                        shared_objects=sorted(seed_labels & labels)
                        if fingerprint and fingerprint.method == "objects"
                        else [],
                        fingerprint=fingerprint,
                    ),
                    photo.date,
                )
            )

        def _order(item: tuple[SimilarPhoto, datetime | None]):
            candidate, date = item
            return (date or datetime.max, candidate.photo.id or 0)

        results.sort(key=_order)
        return [candidate for candidate, _ in results]
