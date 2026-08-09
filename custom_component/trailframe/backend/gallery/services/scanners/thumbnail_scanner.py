from gallery.models.photo import Photo
from gallery.services.scanners.scanner import Scanner
from gallery.services.thumbnail_service import ThumbnailService


class ThumbnailScanner(Scanner):
    def __init__(self):
        super().__init__("Thumbnail")

    def accept(self, photo: Photo) -> bool:
        return not ThumbnailService.exists(photo)

    def scan(self, photo: Photo) -> None:
        ThumbnailService.generate_all(photo)
