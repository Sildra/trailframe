"""Local contrast processor: CLAHE on the luminance channel."""

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


@dataclass(frozen=True)
class LocalContrastSettings:
    """Settings of ``processing.local_contrast``."""

    enabled: bool = False
    clip_limit: float = 2.0
    tile_grid: int = 8
    strength: float = 1.0

    @classmethod
    def from_node(cls, node: Node) -> LocalContrastSettings:
        return cls(
            enabled=as_bool(node.get_path_value("enabled", "Apply CLAHE local contrast", cls.enabled)),
            clip_limit=float(node.get_path_value("clip_limit", "CLAHE contrast limit", cls.clip_limit)),
            tile_grid=int(node.get_path_value("tile_grid", "CLAHE tile grid size", cls.tile_grid)),
            strength=float(node.get_path_value("strength", "How much of CLAHE to blend in", cls.strength)),
        )


class LocalContrastProcessor(Processor):
    """Boosts local detail without amplifying the global tone curve.

    Contrast Limited Adaptive Histogram Equalization runs on the L channel of
    LAB, leaving colour untouched. The result is blended by ``strength`` so the
    effect can be dialled back.
    """

    step = "local_contrast"

    def __init__(self) -> None:
        super().__init__("Local contrast")
        self._settings = LocalContrastSettings()

    def configure_(self, config: Node) -> None:
        node = config.get_node("processing.local_contrast", "Local contrast (CLAHE)")
        self._settings = LocalContrastSettings.from_node(node)
        self._enabled = self._settings.enabled

    def execute(self, image: Image.Image, context: ProcessingContext) -> ProcessorResult:
        settings = self._settings
        pixels, alpha = to_rgb_array(image)
        lab = cv2.cvtColor(pixels, cv2.COLOR_RGB2LAB)
        lightness, a, b = cv2.split(lab)

        grid = max(1, settings.tile_grid)
        clip = max(0.01, settings.clip_limit)
        enhanced = cv2.createCLAHE(clipLimit=clip, tileGridSize=(grid, grid)).apply(lightness)

        strength = max(0.0, min(1.0, settings.strength))

        if strength < 1.0:
            enhanced = lightness.astype("float32") + strength * (enhanced.astype("float32") - lightness)

        result = cv2.cvtColor(cv2.merge([enhanced.astype("uint8"), a, b]), cv2.COLOR_LAB2RGB)

        return ProcessorResult(
            from_rgb_array(result, alpha),
            {
                "step": self.step,
                "summary": "CLAHE",
                "details": {
                    "Method": "CLAHE",
                    "Clip limit": f"{settings.clip_limit:.2f}",
                    "Tiles": f"{grid} × {grid}",
                    "Strength": f"{settings.strength:.0%}",
                },
                "meta": {"clip_limit": settings.clip_limit, "tile_grid": grid, "strength": settings.strength},
            },
        )
