from gallery.models.photo import Photo
from gallery.services.folder_service import FolderService
from gallery.services.scanners.scanner import Scanner


class PerceptualHashScanner(Scanner):
    def __init__(self) -> None:
        super().__init__("PerceptualHash")
        self.needs_tracking = True

    def accept(self, photo: Photo) -> bool:
        return photo.phash is None

    def scan(self, photo: Photo) -> None:
        import imagehash
        from PIL import Image

        image = Image.open(FolderService.resolve(photo.path))
        photo.phash = imagehash.phash(image).hash.flatten().tobytes()
