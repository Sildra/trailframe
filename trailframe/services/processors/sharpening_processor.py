"""Sharpening processor: thresholded unsharp mask."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

from trailframe.services.core.configuration_service import Node
from trailframe.services.processors.processor import (
    ProcessingContext,
    Processor,
    ProcessorResult,
    as_bool,
    from_rgb_array,
    to_rgb_array,
)


@dataclass(frozen=True)
class SharpeningSettings:
    """Settings of ``processing.sharpening``."""

    enabled: bool = False
    radius: float = 1.0
    amount: float = 0.5
    threshold: float = 2.0

    @classmethod
    def from_node(cls, node: Node) -> SharpeningSettings:
        return cls(
            enabled=as_bool(node.get_path_value("enabled", "Sharpen the alternatives", cls.enabled)),
            radius=float(node.get_path_value("radius", "Unsharp mask radius", cls.radius)),
            amount=float(node.get_path_value("amount", "Unsharp mask amount", cls.amount)),
            threshold=float(node.get_path_value("threshold", "Ignore differences below this value", cls.threshold)),
        )


class SharpeningProcessor(Processor):
    """Adds a high-pass detail layer back to the image.

    Running after the rescale keeps the mask tied to the delivered pixel size.
    The optional threshold suppresses low-amplitude differences so smooth areas
    and noise are not sharpened along with real edges.
    """

    step = "sharpening"

    def __init__(self) -> None:
        super().__init__("Sharpening")
        self._settings = SharpeningSettings()

    def configure_(self, config: Node) -> None:
        node = config.get_node("processing.sharpening", "Sharpening")
        self._settings = SharpeningSettings.from_node(node)
        self._enabled = self._settings.enabled

    def execute(self, image: Image.Image, context: ProcessingContext) -> ProcessorResult:
        settings = self._settings
        pixels, alpha = to_rgb_array(image)
        radius = max(0.1, settings.radius)
        blur = cv2.GaussianBlur(pixels, (0, 0), radius)
        difference = pixels.astype("float32") - blur.astype("float32")

        threshold = max(0.0, settings.threshold)

        if threshold > 0:
            detail = np.max(np.abs(difference), axis=2)
            difference[detail <= threshold] = 0.0

        amount = max(0.0, min(3.0, settings.amount))
        result = from_rgb_array(pixels.astype("float32") + amount * difference, alpha)

        return ProcessorResult(
            result,
            {
                "step": self.step,
                "summary": "Unsharp mask",
                "details": {
                    "Method": "Unsharp mask",
                    "Radius": f"{settings.radius:.2f}",
                    "Amount": f"{settings.amount:.2f}",
                    "Threshold": f"{settings.threshold:.1f}",
                },
                "meta": {"radius": settings.radius, "amount": settings.amount, "threshold": settings.threshold},
            },
        )
