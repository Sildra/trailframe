import math
from pathlib import Path

import cv2

from gallery.models.photo import Photo
from gallery.services.scanners.scanner import Scanner


class BrisqueScanner(Scanner):
    def __init__(self):
        super().__init__("Brisque")
        folder = Path(__file__).parent
        self._model = str(folder / "brisque_model_live.yml")
        self._range = str(folder / "brisque_range_live.yml")

    def accept(self, photo: Photo) -> bool:
        return False
        return "brisque" not in photo.scores

    def scan(self, photo: Photo) -> None:
        return
        image = cv2.imread(str(photo.path), cv2.IMREAD_COLOR)
        score = cv2.quality.QualityBRISQUE_compute(image, self._model, self._range)[0]

        if math.isfinite(score):
            photo.scores["brisque"] = round(score, 2)
