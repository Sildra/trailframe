from typing import Any

import imagehash

from trailframe.services.scanners.scanner import Scanner


class PerceptualHashScanner(Scanner):
    def __init__(self) -> None:
        super().__init__("PerceptualHash")

    def accept_(self, item: Any) -> bool:
        return item.photo.phash is None

    async def executePhoto(self, item) -> bool:
        image = item.image

        if image is None:
            return False

        photo = item.photo

        photo.phash = imagehash.phash(image).hash.flatten().tobytes()
        self.add_scanner(photo)

        return True
