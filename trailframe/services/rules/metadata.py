from __future__ import annotations

import re
from typing import Any

from trailframe.models.photo import Photo

MISSING = object()
"""Sentinel returned by `simple_value` for a field it does not read."""


def simple_value(photo: Photo, field: str) -> Any:
    """The value of one of the `Photo` columns a rule can compare against."""
    if field == "filename":
        return photo.filename
    if field == "file_size":
        return photo.file_size
    if field == "is_favorite":
        return bool(photo.is_favorite)
    if field == "location":
        return photo.location
    if field == "country":
        return photo.country
    if field == "latitude":
        return photo.latitude
    if field == "longitude":
        return photo.longitude
    if field == "tags":
        return list(photo.tags or [])
    if field == "scanners":
        return list(photo.scanners or [])
    if field == "date":
        return photo.date.date().isoformat() if photo.date else None
    if field == "width":
        return image_size(photo)[0]
    if field == "height":
        return image_size(photo)[1]
    if field == "orientation":
        width, height = image_size(photo)

        if not width or not height:
            return None

        if width == height:
            return "square"

        return "landscape" if width > height else "portrait"

    return MISSING


def exif_value(photo: Photo, field: str) -> Any:
    """The EXIF value named by `field`, e.g. `exif.Make` or a nested path."""
    exif = photo.exif or {}

    if field == "exif":
        return exif

    current: Any = exif

    for part in field.split(".", 1)[1].split("."):
        if not isinstance(current, dict):
            return None

        current = current.get(part)

    return current


def image_size(photo: Photo) -> tuple[int | None, int | None]:
    """The pixel size of the main file, falling back to the EXIF dimensions."""
    main = photo.main()

    if main.width and main.height:
        return main.width, main.height

    exif = photo.exif or {}
    width = as_int(exif.get("ExifImageWidth") or exif.get("ImageWidth"))
    height = as_int(exif.get("ExifImageHeight") or exif.get("ImageLength") or exif.get("ImageHeight"))

    if width and height:
        orientation = as_int(exif.get("Orientation"))

        # EXIF orientations 5-8 swap the axes.
        if orientation in (5, 6, 7, 8):
            width, height = height, width

        return width, height

    return width, height


def detections(photo: Photo, label: str | None, ignore_constraints: bool = False) -> list[dict[str, float]]:
    """The detections of the photo, with `confidence` and `surface` read as stored."""
    wanted = str(label).strip().lower() if label else None
    objects = photo.objects or {}
    found: list[dict[str, float]] = []

    for raw in objects.get("detections") or []:
        if not isinstance(raw, dict):
            continue

        detected = str(raw.get("label") or "")

        if wanted is not None and detected.lower() != wanted:
            continue

        confidence = as_float(raw.get("confidence"))

        if confidence is None:
            confidence = 0.0

        surface = as_float(raw.get("surface")) or 0.0

        found.append(
            {
                "label": detected,  # type: ignore[dict-item]
                "confidence": confidence,
                "score": confidence,
                "surface": surface,
            }
        )

    return found


def as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return int(value)

    match = re.match(r"\s*(\d+)", str(value))

    return int(match.group(1)) if match else None


def as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None
