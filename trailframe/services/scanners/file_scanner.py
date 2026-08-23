import os

from trailframe.models.photo import Photo
from trailframe.services.folder_service import FolderService
from trailframe.services.scanners.scanner import Scanner


class FileScanner(Scanner):
    def __init__(self):
        super().__init__("File")

    def accept(self, photo: Photo) -> bool:
        return photo.filename is None or photo.file_size is None

    def scan(self, photo: Photo) -> None:
        source = FolderService.resolve(photo.path)
        photo.filename = source.name

        try:
            photo.file_size = os.path.getsize(source)
        except OSError:
            photo.file_size = None
