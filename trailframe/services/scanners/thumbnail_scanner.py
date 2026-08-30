
from trailframe.models.photo import Photo
from trailframe.services.photos.thumbnail_service import ThumbnailService
from trailframe.services.pipelines.item import Item
from trailframe.services.scanners.scanner import Scanner


class ThumbnailScanner(Scanner):
    def __init__(self):
        super().__init__("Thumbnail")

    def accept_(self, photo: Photo) -> bool:
        return not ThumbnailService.exists(photo)

    async def executePhoto(self, item: Item) -> bool:
        ThumbnailService.generate_all(item.photo)

        return False
