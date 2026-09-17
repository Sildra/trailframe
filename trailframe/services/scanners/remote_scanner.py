from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from trailframe.models.photo import Photo
from trailframe.services.core.thread_pool_service import ThreadPoolService
from trailframe.services.photos.photo_service import PhotoService
from trailframe.services.pipelines.item import Item
from trailframe.services.scanners import can_run_remotely
from trailframe.services.scanners.scanner import ForceFlag, Scanner


class RemoteScanner(Scanner):
    """Runs scanners on a remote Trailframe server and applies the results locally.

    `accept` runs locally first (same gating as the delegated scanners); only when
    accepted is the photo uploaded to the remote `/api/pipeline/remote-scan`
    endpoint, which executes the delegated scanners and returns the enriched photo.
    A `ForceFlag` naming any delegated scanner forces that scanner on the remote
    server (by-passing its `accept_` gating there).
    """

    _can_be_disabled = False

    def __init__(self, remote: str = "", scanner_names: list[str] | None = None):
        super().__init__("Remote")
        self._remote = self._normalize(remote)
        self._scanner_names = [name for name in (scanner_names or []) if can_run_remotely(name)]
        self._forced_names: list[str] = []

    @staticmethod
    def _normalize(remote: str) -> str:
        value = remote.strip().rstrip("/")

        if value and not value.startswith(("http://", "https://")):
            value = f"http://{value}"

        return value

    @classmethod
    def _delegated_scanner(cls, name: str):
        from trailframe.services.scanners import create_scanner

        return create_scanner(name)

    def accept(self, item: Any) -> bool:
        if isinstance(item, ForceFlag):
            forced = set(item.scanners or [])
            self._forced_names = [name for name in self._scanner_names if name in forced]
            self._forced = bool(self._forced_names)
            return False

        if self._forced:
            return True

        if isinstance(item, Photo):
            return self.accept_(item)
        if isinstance(item, Item):
            return self.accept_(item.photo)

        return False

    def accept_(self, photo: Photo) -> bool:
        for name in self._scanner_names:
            scanner = self._delegated_scanner(name)

            if scanner is not None and scanner.accept(photo):
                return True

        return False

    async def executePhoto(self, item: Item) -> bool:
        photo = item.photo
        source = PhotoService.resolve(photo)

        if not self._remote or not self._scanner_names or not source.is_file():
            return False

        url = f"{self._remote}/api/pipeline/remote-scan"
        result = await ThreadPoolService.run(self._post, url, source, self._scanner_names, self._forced_names)

        return self._apply(photo, item, result)

    @staticmethod
    def _post(url: str, path: Path, scanner_names: list[str], forced: list[str] | None = None) -> dict | None:
        with path.open("rb") as handle:
            response = requests.post(
                url,
                files={"file": (path.name, handle, "application/octet-stream")},
                data={"scanners": ",".join(scanner_names), "forced": ",".join(forced or [])},
                timeout=120,
            )
            response.raise_for_status()

            return response.json()

    def _apply(self, photo: Photo, item: Item, result: dict | None) -> bool:
        if not isinstance(result, dict):
            return False

        requested = set(self._scanner_names)

        if "EXIF" in requested:
            photo.exif = result.get("exif") or {}

            date_value = result.get("date")
            if date_value:
                try:
                    photo.date = datetime.fromisoformat(str(date_value))
                except ValueError:
                    pass

            if result.get("latitude") is not None:
                photo.latitude = result["latitude"]
            if result.get("longitude") is not None:
                photo.longitude = result["longitude"]
            if result.get("location_source"):
                photo.location_source = result["location_source"]

        if "Object" in requested:
            photo.objects = result.get("objects") or []

        if "PerceptualHash" in requested:
            phash = result.get("phash")

            if phash:
                new_phash = bytes.fromhex(phash)

                if photo.phash != new_phash:
                    photo.phash = new_phash
                    item.phash_changed = True

        if "Location" in requested:
            if result.get("country") is not None:
                photo.country = result["country"]
            if result.get("location") is not None:
                photo.location = result["location"]
            if result.get("wireframe") is not None:
                photo.wireframe = result["wireframe"]

        if result.get("tags") is not None:
            photo.tags = result["tags"]
        if result.get("scores") is not None:
            photo.scores = result["scores"]

        tracked = set(photo.scanners or [])
        tracked.update(name for name in result.get("scanners") or [] if name not in ("File", "Database"))
        photo.scanners = sorted(tracked)

        return True
