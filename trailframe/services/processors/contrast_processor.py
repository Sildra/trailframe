"""Contrast processor: adaptive tone curve and S-curve."""

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
    analysis_copy,
    as_bool,
    from_rgb_array,
    to_rgb_array,
)

S_CURVE = "s_curve"
ADAPTIVE = "adaptive"
METHODS = frozenset({S_CURVE, ADAPTIVE})


@dataclass(frozen=True)
class ContrastSettings:
    """Settings of ``processing.contrast``."""

    enabled: bool = False
    method: str = S_CURVE
    strength: float = 0.5
    low_percentile: float = 5.0
    high_percentile: float = 95.0
    analysis_max_dimension: int = 512

    @classmethod
    def from_node(cls, node: Node) -> ContrastSettings:
        method = str(node.get_path_value("method", f"{S_CURVE} or {ADAPTIVE}", cls.method)).lower()

        if method not in METHODS:
            method = cls.method

        return cls(
            enabled=as_bool(node.get_path_value("enabled", "Apply a tone curve", cls.enabled)),
            method=method,
            strength=float(node.get_path_value("strength", "How much of the curve to apply", cls.strength)),
            low_percentile=float(
                node.get_path_value(
                    "low_percentile", "Black point percentile for adaptive contrast", cls.low_percentile
                )
            ),
            high_percentile=float(
                node.get_path_value(
                    "high_percentile", "White point percentile for adaptive contrast", cls.high_percentile
                )
            ),
            analysis_max_dimension=int(
                node.get_path_value(
                    "analysis_max_dimension", "Longest edge used for tone estimation", cls.analysis_max_dimension
                )
            ),
        )


@dataclass(frozen=True)
class ContrastDecision:
    """Tone endpoints measured once for the photo."""

    black: float
    white: float


class ContrastProcessor(Processor):
    """Applies either a smooth S-curve or a scene-adaptive tone stretch.

    The adaptive method measures the luminance percentiles of a downscaled copy
    once in :meth:`prepare`, so every target size uses the same tone endpoints.
    The result is blended with the original using ``strength``.
    """

    step = "contrast"

    def __init__(self) -> None:
        super().__init__("Contrast")
        self._settings = ContrastSettings()

    def configure_(self, config: Node) -> None:
        node = config.get_node("processing.contrast", "Tonal contrast")
        self._settings = ContrastSettings.from_node(node)
        self._enabled = self._settings.enabled

    def prepare(self, image: Image.Image, context: ProcessingContext) -> None:
        context.data[self.name] = self._detect(image)

    def execute(self, image: Image.Image, context: ProcessingContext) -> ProcessorResult:
        decision = context.data.get(self.name)

        if not isinstance(decision, ContrastDecision):
            decision = self._detect(image)

        pixels, alpha = to_rgb_array(image)
        values = pixels.astype("float32") / 255.0

        if self._settings.method == ADAPTIVE:
            span = max(decision.white - decision.black, 1.0)
            curved = np.clip((values * 255.0 - decision.black) / span, 0.0, 1.0)
        else:
            curved = values * values * (3.0 - 2.0 * values)

        strength = max(0.0, min(1.0, self._settings.strength))
        blended = values + strength * (curved - values)

        return ProcessorResult(from_rgb_array(blended * 255.0, alpha), self._record(decision))

    def _detect(self, image: Image.Image) -> ContrastDecision:
        settings = self._settings
        sample, _ = to_rgb_array(analysis_copy(image, settings.analysis_max_dimension))
        gray = cv2.cvtColor(sample, cv2.COLOR_RGB2GRAY)

        if gray.size == 0:
            return ContrastDecision(0.0, 255.0)

        low = max(0.0, min(100.0, settings.low_percentile))
        high = max(0.0, min(100.0, settings.high_percentile))

        if high <= low:
            high = min(100.0, low + 10.0)

        black, white = np.percentile(gray, [low, high])

        return ContrastDecision(float(black), float(white))

    def _record(self, decision: ContrastDecision) -> dict:
        details = {
            "Method": "Adaptive tone curve" if self._settings.method == ADAPTIVE else "S-curve",
            "Strength": f"{self._settings.strength:.0%}",
        }

        if self._settings.method == ADAPTIVE:
            details["Black point"] = f"{decision.black:.0f}"
            details["White point"] = f"{decision.white:.0f}"

        return {
            "step": self.step,
            "summary": details["Method"],
            "details": details,
            "meta": {
                "method": self._settings.method,
                "strength": self._settings.strength,
                "black": round(decision.black, 2),
                "white": round(decision.white, 2),
            },
        }
