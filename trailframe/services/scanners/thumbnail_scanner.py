from typing import Any

from trailframe.services.photos.thumbnail_service import ThumbnailService
from trailframe.services.scanners.scanner import Scanner


class ThumbnailScanner(Scanner):
    def __init__(self):
        super().__init__("Thumbnail")

    def accept_(self, item: Any) -> bool:
        return not ThumbnailService.exists(item.photo)

    async def executePhoto(self, item) -> bool:
        ThumbnailService.generate_all(item.photo)

        return False
