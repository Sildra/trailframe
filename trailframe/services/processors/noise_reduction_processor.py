"""Noise reduction processor: bilateral filter or non-local means."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
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

BILATERAL = "bilateral"
NL_MEANS = "nl_means"
METHODS = frozenset({BILATERAL, NL_MEANS})


@dataclass(frozen=True)
class NoiseReductionSettings:
    """Settings of ``processing.noise_reduction``."""

    enabled: bool = False
    method: str = BILATERAL
    radius: int = 5
    sigma_color: float = 35.0
    sigma_space: float = 35.0
    strength: float = 10.0

    @classmethod
    def from_node(cls, node: Node) -> NoiseReductionSettings:
        method = str(node.get_path_value("method", f"{BILATERAL} or {NL_MEANS}", cls.method)).lower()

        if method not in METHODS:
            method = cls.method

        return cls(
            enabled=as_bool(node.get_path_value("enabled", "Reduce image noise", cls.enabled)),
            method=method,
            radius=int(node.get_path_value("radius", "Bilateral neighbourhood size", cls.radius)),
            sigma_color=float(node.get_path_value("sigma_color", "Bilateral colour sigma", cls.sigma_color)),
            sigma_space=float(node.get_path_value("sigma_space", "Bilateral spatial sigma", cls.sigma_space)),
            strength=float(node.get_path_value("strength", "Non-local means strength", cls.strength)),
        )


class NoiseReductionProcessor(Processor):
    """Smooths noise while keeping edges.

    The bilateral filter is fast and preserves edges using both colour and
    distance weights. Non-local means is slower but better on detailed textures;
    it is opt-in because it can dominate the processing time of large photos.
    """

    step = "noise_reduction"

    def __init__(self) -> None:
        super().__init__("Noise reduction")
        self._settings = NoiseReductionSettings()

    def configure_(self, config: Node) -> None:
        node = config.get_node("processing.noise_reduction", "Noise reduction")
        self._settings = NoiseReductionSettings.from_node(node)
        self._enabled = self._settings.enabled

    def execute(self, image: Image.Image, context: ProcessingContext) -> ProcessorResult:
        settings = self._settings
        pixels, alpha = to_rgb_array(image)

        if settings.method == NL_MEANS:
            h = max(1.0, min(30.0, settings.strength))
            result = cv2.fastNlMeansDenoisingColored(pixels, None, h, h, 7, 21)
            details = {"Method": "Non-local means", "Strength": f"{settings.strength:.1f}"}
            meta = {"method": NL_MEANS, "strength": settings.strength}
        else:
            diameter = max(1, settings.radius) | 1
            sigma_color = max(1.0, settings.sigma_color)
            sigma_space = max(1.0, settings.sigma_space)
            result = cv2.bilateralFilter(pixels, diameter, sigma_color, sigma_space)
            details = {
                "Method": "Bilateral",
                "Radius": str(diameter),
                "Colour sigma": f"{settings.sigma_color:.1f}",
                "Spatial sigma": f"{settings.sigma_space:.1f}",
            }
            meta = {
                "method": BILATERAL,
                "radius": diameter,
                "sigma_color": settings.sigma_color,
                "sigma_space": settings.sigma_space,
            }

        return ProcessorResult(
            from_rgb_array(result, alpha),
            {"step": self.step, "summary": details["Method"], "details": details, "meta": meta},
        )
