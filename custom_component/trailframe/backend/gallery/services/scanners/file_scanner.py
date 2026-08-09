import os
from pathlib import Path

from gallery.models.photo import Photo
from gallery.services.scanners.scanner import Scanner


class FileScanner(Scanner):
    def __init__(self):
        super().__init__("File")

    def accept(self, photo: Photo) -> bool:
        return photo.filename is None or photo.file_size is None

    def scan(self, photo: Photo) -> None:
        photo.filename = Path(photo.path).name

        try:
            photo.file_size = os.path.getsize(photo.path)
        except OSError:
            photo.file_size = None
