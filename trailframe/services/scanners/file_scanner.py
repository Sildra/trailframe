import os
from typing import Any

from trailframe.services.photos.photo_service import PhotoService
from trailframe.services.scanners.scanner import Scanner


class FileScanner(Scanner):
    def __init__(self):
        super().__init__("File")

    def accept_(self, item: Any) -> bool:
        return item.photo.filename is None or item.photo.file_size is None

    async def executePhoto(self, item) -> bool:
        photo = item.photo
        changed = photo.filename is None or photo.file_size is None

        source = PhotoService.resolve(photo)
        photo.filename = source.name

        try:
            photo.file_size = os.path.getsize(source)
        except OSError:
            photo.file_size = None

        return changed
