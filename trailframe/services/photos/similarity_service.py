import logging
import math
from datetime import datetime, timedelta
from typing import ClassVar

from sqlalchemy import select

from trailframe.models.photo import Photo, PhotoDetail
from trailframe.models.similarity import SimilarPhoto
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.service import Service


class SimilarityError(Exception):
    """A user-correctable problem with a similarity request."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def _hash_value(raw: bytes | None) -> int | None:
    """Read both the packed and legacy pHash formats as a 64-bit integer."""

    if raw is None:
        return None

    if len(raw) == 8:
        return int.from_bytes(raw, "big")

    if len(raw) == 64 and all(byte in (0, 1) for byte in raw):
        value = 0
        for byte in raw:
            value = (value << 1) | byte
        return value

    return None


def _object_sets(photo: Photo) -> tuple[set[str], set[str]]:
    """Return object labels and coarse label/shape signatures.

    A signature keeps the label, a quantised box aspect ratio and a quantised
    surface, so two detections of the same kind and rough shape match even when
    their source images have different pixel sizes.
    """

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
        aspect_bucket = None
        size_bucket = None
        box = detection.get("box")

        if isinstance(box, (list, tuple)) and len(box) >= 4:
            try:
                width = abs(float(box[2]) - float(box[0]))
                height = abs(float(box[3]) - float(box[1]))
            except (TypeError, ValueError):
                width = height = 0.0

            if width > 0 and height > 0:
                aspect_bucket = max(-4, min(4, round(math.log2(width / height) * 2)))

        surface = detection.get("surface")

        if isinstance(surface, (int, float)) and not isinstance(surface, bool):
            size_bucket = max(0, min(10, round(float(surface) * 10)))

        signatures.add(f"{label}|{aspect_bucket}|{size_bucket}")

    return labels, signatures


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0

    union = left | right
    return len(left & right) / len(union) if union else 0.0


class SimilarityService(Service):
    """Finds photos related to a seed by time, objects and perceptual hash."""

    _requires: ClassVar[tuple[str, ...]] = ("DatabaseService",)

    @classmethod
    async def candidates(
        cls, photo_id: int, window_seconds: int, max_hamming: int, min_object_overlap: float
    ) -> list[SimilarPhoto]:
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

        seed_hash = _hash_value(seed.phash)
        seed_labels, seed_signatures = _object_sets(seed)
        results: list[tuple[SimilarPhoto, datetime | None]] = []

        for photo in photos:
            distance = None
            hash_score = None
            photo_hash = _hash_value(photo.phash)

            if seed_hash is not None and photo_hash is not None:
                distance = (seed_hash ^ photo_hash).bit_count()

                if distance <= max_hamming:
                    hash_score = 1 - distance / max(1, max_hamming)

            labels, signatures = _object_sets(photo)
            shared = sorted(seed_labels & labels)
            object_score = None

            if seed_labels and labels:
                signature_score = _jaccard(seed_signatures, signatures)
                label_score = _jaccard(seed_labels, labels)
                object_score = 0.6 * signature_score + 0.4 * label_score if seed_signatures else label_score

            similar = (hash_score is not None and hash_score >= 0) or (
                object_score is not None and object_score >= min_object_overlap and bool(shared)
            )

            if similar:
                parts = [
                    (score, weight) for score, weight in ((hash_score, 0.6), (object_score, 0.4)) if score is not None
                ]
                score = sum(value * weight for value, weight in parts) / sum(weight for _, weight in parts)
            else:
                score = 0.0

            results.append(
                (
                    SimilarPhoto(
                        photo=PhotoDetail.from_photo(photo),
                        similar=similar,
                        score=round(score, 4),
                        phash_distance=distance,
                        shared_objects=shared,
                    ),
                    photo.date,
                )
            )

        def _order(item: tuple[SimilarPhoto, datetime | None]):
            candidate, date = item
            return (date or datetime.max, candidate.photo.id or 0)

        results.sort(key=_order)
        return [candidate for candidate, _ in results]
