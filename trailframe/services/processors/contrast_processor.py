"""Contrast processor: adaptive tone curve and S-curve."""

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
    analysis_copy,
    as_bool,
    from_rgb_array,
    to_rgb_array,
    with_overrides,
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
class ContrastOverride:
    """Per-photo override of the contrast step."""

    enabled: bool | None = None
    method: str | None = None
    strength: float | None = None
    low_percentile: float | None = None
    high_percentile: float | None = None
    analysis_max_dimension: int | None = None


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
    overridable = True

    def __init__(self) -> None:
        super().__init__("Contrast")
        self._settings = ContrastSettings()

    def configure_(self, config: Node) -> None:
        node = config.get_node("processing.contrast", "Tonal contrast")
        self._settings = ContrastSettings.from_node(node)
        self._enabled = self._settings.enabled

    def prepare(self, image: Image.Image, context: ProcessingContext) -> None:
        settings = with_overrides(self._settings, context.overrides.get(self.name))
        context.data[self.name] = self._detect(image, settings)

    def execute(self, image: Image.Image, context: ProcessingContext) -> ProcessorResult:
        settings = with_overrides(self._settings, context.overrides.get(self.name))
        decision = context.data.get(self.name)

        if not isinstance(decision, ContrastDecision):
            decision = self._detect(image, settings)

        pixels, alpha = to_rgb_array(image)
        values = pixels.astype("float32") / 255.0

        if settings.method == ADAPTIVE:
            span = max(decision.white - decision.black, 1.0)
            curved = np.clip((values * 255.0 - decision.black) / span, 0.0, 1.0)
        else:
            curved = values * values * (3.0 - 2.0 * values)

        strength = max(0.0, min(1.0, settings.strength))
        blended = values + strength * (curved - values)

        return ProcessorResult(from_rgb_array(blended * 255.0, alpha), self._record(settings, decision))

    def validate_override(self, override) -> str | None:
        if not isinstance(override, ContrastOverride):
            return None

        if override.method is not None and override.method not in METHODS:
            return f"Unknown contrast method '{override.method}'."

        if override.strength is not None and (
            not math.isfinite(override.strength) or not 0.0 <= override.strength <= 1.0
        ):
            return "Strength must be between 0 and 1."

        for name, value in (("Low percentile", override.low_percentile), ("High percentile", override.high_percentile)):
            if value is not None and (not math.isfinite(value) or not 0.0 <= value <= 100.0):
                return f"{name} must be between 0 and 100."

        if (
            override.low_percentile is not None
            and override.high_percentile is not None
            and override.low_percentile >= override.high_percentile
        ):
            return "The low percentile must be below the high percentile."

        if override.analysis_max_dimension is not None and not 1 <= override.analysis_max_dimension <= 8192:
            return "The analysis size must be between 1 and 8192 px."

        return None

    def _detect(self, image: Image.Image, settings: ContrastSettings) -> ContrastDecision:
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

    def _record(self, settings: ContrastSettings, decision: ContrastDecision) -> dict:
        details = {
            "Method": "Adaptive tone curve" if settings.method == ADAPTIVE else "S-curve",
            "Strength": f"{settings.strength:.0%}",
        }

        if settings.method == ADAPTIVE:
            details["Black point"] = f"{decision.black:.0f}"
            details["White point"] = f"{decision.white:.0f}"

        return {
            "step": self.step,
            "summary": details["Method"],
            "details": details,
            "meta": {
                "method": settings.method,
                "strength": settings.strength,
                "black": round(decision.black, 2),
                "white": round(decision.white, 2),
            },
        }
