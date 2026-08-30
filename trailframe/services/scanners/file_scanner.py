import os
from typing import Any

from trailframe.models.photo import Photo
from trailframe.services.core.configuration_service import Node
from trailframe.services.photos.photo_service import PhotoService
from trailframe.services.pipelines.item import Item
from trailframe.services.scanners.scanner import Scanner


class FileScanner(Scanner):
    def __init__(self):
        super().__init__("File")
        self._can_be_disabled = False


    def accept_(self, photo: Photo) -> bool:
        return True

    async def executePhoto(self, item: Item) -> bool:
        photo = item.photo
        changed = photo.filename is None or photo.file_size is None

        source = PhotoService.resolve(photo)
        photo.filename = source.name

        try:
            photo.file_size = os.path.getsize(source)
        except OSError:
            photo.file_size = None

        return changed
