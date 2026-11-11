from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ORIGINAL = "original"
ALTERNATIVE = "alternative"


@dataclass(frozen=True)
class PhotoFile:
    """A file belonging to a photo: the original archive file or a processed alternative.

    Original files live in the photos folder and are addressed by `Photo.path`;
    alternatives live in the processed folder and are stored as plain entries in
    `Photo.alternatives`.
    """

    kind: str
    path: str
    filename: str | None = None
    file_size: int | None = None
    width: int | None = None
    height: int | None = None
    target_size: int | None = None
    main: bool = False

    @property
    def is_original(self) -> bool:
        return self.kind == ORIGINAL

    @classmethod
    def from_alternative(cls, entry: dict[str, Any]) -> PhotoFile:
        """Build a file descriptor from one entry of `Photo.alternatives`."""
        return cls(
            kind=ALTERNATIVE,
            path=str(entry.get("path") or ""),
            filename=entry.get("filename"),
            file_size=entry.get("file_size"),
            width=entry.get("width"),
            height=entry.get("height"),
            target_size=entry.get("target_size"),
            main=bool(entry.get("main")),
        )
