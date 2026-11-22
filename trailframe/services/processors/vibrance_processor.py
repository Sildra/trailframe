"""Vibrance processor: adaptive saturation in LAB colour space."""

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
class VibranceSettings:
    """Settings of ``processing.vibrance``."""

    enabled: bool = False
    strength: float = 0.4

    @classmethod
    def from_node(cls, node: Node) -> VibranceSettings:
        return cls(
            enabled=as_bool(node.get_path_value("enabled", "Boost muted colours", cls.enabled)),
            strength=float(node.get_path_value("strength", "Vibrance amount", cls.strength)),
        )


class VibranceProcessor(Processor):
    """Raises saturation mostly where colours are already muted.

    Saturation is measured as LAB chroma relative to the neutral axis. The boost
    tapers off for already vivid colours and near-black/near-white pixels, which
    keeps skin tones and highlights from becoming garish.
    """

    step = "vibrance"

    def __init__(self) -> None:
        super().__init__("Vibrance")
        self._settings = VibranceSettings()

    def configure_(self, config: Node) -> None:
        node = config.get_node("processing.vibrance", "Adaptive saturation")
        self._settings = VibranceSettings.from_node(node)
        self._enabled = self._settings.enabled

    def execute(self, image: Image.Image, context: ProcessingContext) -> ProcessorResult:
        pixels, alpha = to_rgb_array(image)
        lab = cv2.cvtColor(pixels, cv2.COLOR_RGB2LAB).astype("float32")
        lightness = lab[:, :, 0] / 255.0
        a = lab[:, :, 1] - 128.0
        b = lab[:, :, 2] - 128.0

        chroma = np.sqrt(a * a + b * b) / 181.0
        hue_weight = 1.0 - np.clip(chroma, 0.0, 1.0)
        tone_weight = 1.0 - np.abs(2.0 * lightness - 1.0)
        factor = 1.0 + max(0.0, min(1.0, self._settings.strength)) * hue_weight * np.clip(tone_weight, 0.0, 1.0)

        lab[:, :, 1] = 128.0 + a * factor
        lab[:, :, 2] = 128.0 + b * factor
        result = cv2.cvtColor(lab.astype("uint8"), cv2.COLOR_LAB2RGB)

        return ProcessorResult(
            from_rgb_array(result, alpha),
            {
                "step": self.step,
                "summary": "Adaptive LAB",
                "details": {"Method": "Adaptive saturation (LAB)", "Strength": f"{self._settings.strength:.0%}"},
                "meta": {"strength": self._settings.strength},
            },
        )
