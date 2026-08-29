from pathlib import Path
from threading import Lock
from typing import Any

from trailframe.services.core.configuration_service import Node
from trailframe.services.photos.photo_service import PhotoService
from trailframe.services.scanners.scanner import Scanner

YOLO_MODELS = {
    "Nano": "yolo26n.pt",
    "Small": "yolo26s.pt",
    "Medium": "yolo26m.pt",
    "Large": "yolo26l.pt",
    "Extra Large": "yolo26x.pt",
}


class ObjectScanner(Scanner):
    def __init__(self) -> None:
        super().__init__("Object")
        self._model = None
        self._model_lock = Lock()
        self._model_name = "yolo26n.pt"
        self._models_folder = Path("models")

    def configure_(self, config: Node) -> None:
        self._model_name = config.get_path_value(
            "scanners.Object.model", "YOLO model to use for object detection", "yolo26n.pt"
        )
        self._models_folder = Path(
            config.get_path_value("general.models_folder", "Folder where models are stored", "models")
        )

    def accept_(self, item: Any) -> bool:
        return self.name not in (item.photo.scanners or [])

    async def executePhoto(self, item) -> bool:
        photo = item.photo

        model = self._get_model()
        results = model(str(PhotoService.resolve(photo)), verbose=False)
        detections = []

        for result in results:
            if result.boxes is None:
                continue

            names = result.names

            for box in result.boxes:
                x1, y1, x2, y2 = (round(float(value), 1) for value in box.xyxy[0].tolist())
                label = names.get(int(box.cls[0]), str(int(box.cls[0])))
                confidence = round(float(box.conf[0]), 3)

                detections.append({"label": label, "confidence": confidence, "box": [x1, y1, x2, y2]})

        photo.objects = detections
        self.add_scanner(photo)

        return True

    def _get_model(self):
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    from ultralytics import YOLO
                    from ultralytics.utils import checks

                    model_path = self._models_folder / self._model_name

                    if not model_path.exists():
                        self._models_folder.mkdir(parents=True, exist_ok=True)
                        url = f"https://github.com/ultralytics/assets/releases/download/v8.4.0/{self._model_name}"
                        checks.check_file(url, download_dir=str(self._models_folder))

                    self._model = YOLO(str(model_path))

        return self._model
