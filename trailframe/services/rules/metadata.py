"""Read a photo as a plain JSON-like view and walk declared paths over it.

Rules never touch the `Photo` columns directly: `photo_view` materializes the
handful of derived values (image size, orientation, normalized date, ...) once,
and `walk` follows a dotted path with optional `[key=value]` selectors. Adding a
field is therefore a descriptor line, not an evaluator branch.
"""

from __future__ import annotations

import re
from typing import Any

from trailframe.models.photo import Photo

MISSING = object()
"""Sentinel returned by `walk` for a path that does not resolve."""


def photo_view(photo: Photo) -> dict[str, Any]:
    """The photo as a JSON-like dictionary, with the derived fields filled in."""
    width, height = image_size(photo)

    return {
        "filename": photo.filename,
        "file_size": photo.file_size,
        "is_favorite": bool(photo.is_favorite),
        "location": photo.location,
        "country": photo.country,
        "latitude": photo.latitude,
        "longitude": photo.longitude,
        "tags": photo.tags or [],
        "scanners": photo.scanners or [],
        "date": photo.date.date().isoformat() if photo.date else None,
        "width": width,
        "height": height,
        "orientation": orientation_of(width, height),
        "exif": photo.exif or {},
        "scores": photo.scores or {},
        "objects": (photo.objects or {}).get("detections") or [],
        "processing": photo.processing or [],
        "alternatives": photo.alternatives or [],
    }


def orientation_of(width: int | None, height: int | None) -> str | None:
    """`landscape`, `portrait` or `square`, when the image size is known."""
    if not width or not height:
        return None

    if width == height:
        return "square"

    return "landscape" if width > height else "portrait"


def source_parts(source: str) -> list[str]:
    """Split a source path into its steps: `a.b[step=tilt].c` → `a`, `b`, `[step=tilt]`, `c`."""
    parts: list[str] = []
    buffer = ""
    index = 0

    while index < len(source):
        char = source[index]

        if char == ".":
            if buffer:
                parts.append(buffer)
                buffer = ""
        elif char == "[":
            if buffer:
                parts.append(buffer)
                buffer = ""

            end = source.find("]", index)

            if end < 0:
                return []

            parts.append(source[index : end + 1])
            index = end
        else:
            buffer += char

        index += 1

    if buffer:
        parts.append(buffer)

    return parts


def walk(value: Any, source: str) -> Any:
    """Follow `source` from `value`; any miss, or a selector with 0 or 2+ hits, is MISSING."""
    current = value

    for part in source_parts(source):
        if part.startswith("["):
            key, _, expected = part[1:-1].partition("=")
            entries = current if isinstance(current, list) else []
            wanted = expected.strip().strip('"').strip("'")
            matches = [
                entry for entry in entries if isinstance(entry, dict) and _text(entry.get(key.strip())) == _text(wanted)
            ]

            if len(matches) != 1:
                return MISSING

            current = matches[0]
            continue

        if isinstance(current, dict):
            if part not in current:
                return MISSING

            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            position = int(part)

            if position >= len(current):
                return MISSING

            current = current[position]
        else:
            return MISSING

    return current


def _text(value: Any) -> str:
    return str(value).strip().casefold()


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


__all__ = ["MISSING", "as_float", "as_int", "image_size", "orientation_of", "photo_view", "source_parts", "walk"]
