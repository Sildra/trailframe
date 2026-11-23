"""Sharpening processor: thresholded unsharp mask."""

from __future__ import annotations

import math
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
    with_overrides,
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


@dataclass(frozen=True)
class SharpeningOverride:
    """Per-photo override of the sharpening step."""

    enabled: bool | None = None
    radius: float | None = None
    amount: float | None = None
    threshold: float | None = None


class SharpeningProcessor(Processor):
    """Adds a high-pass detail layer back to the image.

    Running after the rescale keeps the mask tied to the delivered pixel size.
    The optional threshold suppresses low-amplitude differences so smooth areas
    and noise are not sharpened along with real edges.
    """

    step = "sharpening"
    overridable = True

    def __init__(self) -> None:
        super().__init__("Sharpening")
        self._settings = SharpeningSettings()

    def configure_(self, config: Node) -> None:
        node = config.get_node("processing.sharpening", "Sharpening")
        self._settings = SharpeningSettings.from_node(node)
        self._enabled = self._settings.enabled

    def validate_override(self, override) -> str | None:
        if not isinstance(override, SharpeningOverride):
            return None

        if override.radius is not None and (not math.isfinite(override.radius) or not 0.1 <= override.radius <= 10):
            return "Radius must be between 0.1 and 10."

        if override.amount is not None and (not math.isfinite(override.amount) or not 0.0 <= override.amount <= 3.0):
            return "Amount must be between 0 and 3."

        if override.threshold is not None and (
            not math.isfinite(override.threshold) or not 0.0 <= override.threshold <= 50.0
        ):
            return "Threshold must be between 0 and 50."

        return None

    def execute(self, image: Image.Image, context: ProcessingContext) -> ProcessorResult:
        settings = with_overrides(self._settings, context.overrides.get(self.name))
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
