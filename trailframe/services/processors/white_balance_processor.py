"""White balance processor: Gray World detection plus temperature/tint gains."""

from __future__ import annotations

import math
from dataclasses import dataclass

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

GRAY_WORLD = "gray_world"
MANUAL = "manual"
METHODS = frozenset({GRAY_WORLD, MANUAL})


@dataclass(frozen=True)
class WhiteBalanceSettings:
    """Settings of ``processing.white_balance``."""

    enabled: bool = False
    method: str = GRAY_WORLD
    strength: float = 0.6
    temperature: float = 0.0
    tint: float = 0.0
    analysis_max_dimension: int = 512

    @classmethod
    def from_node(cls, node: Node) -> WhiteBalanceSettings:
        method = str(node.get_path_value("method", f"{GRAY_WORLD} or {MANUAL}", cls.method)).lower()

        if method not in METHODS:
            method = cls.method

        return cls(
            enabled=as_bool(node.get_path_value("enabled", "Correct the white balance", cls.enabled)),
            method=method,
            strength=float(node.get_path_value("strength", "How much of the gain to apply", cls.strength)),
            temperature=float(node.get_path_value("temperature", "Warm (+) or cool (-), -1 to 1", cls.temperature)),
            tint=float(node.get_path_value("tint", "Magenta (+) or green (-), -1 to 1", cls.tint)),
            analysis_max_dimension=int(
                node.get_path_value(
                    "analysis_max_dimension", "Longest edge used for Gray World detection", cls.analysis_max_dimension
                )
            ),
        )


@dataclass(frozen=True)
class WhiteBalanceOverride:
    """Per-photo override of the white balance step."""

    enabled: bool | None = None
    method: str | None = None
    strength: float | None = None
    temperature: float | None = None
    tint: float | None = None
    analysis_max_dimension: int | None = None


@dataclass(frozen=True)
class WhiteBalanceDecision:
    """Channel gains detected once for the photo."""

    gains: tuple[float, float, float]
    method: str


class WhiteBalanceProcessor(Processor):
    """Neutralises the scene cast before the tone corrections.

    Gray World samples a downscaled copy and clips extreme pixels so highlights
    and shadows do not skew the estimate. The detected gains are combined with
    the manual temperature/tint gains and blended by ``strength``.
    """

    step = "white_balance"
    overridable = True

    def __init__(self) -> None:
        super().__init__("White balance")
        self._settings = WhiteBalanceSettings()

    def configure_(self, config: Node) -> None:
        node = config.get_node("processing.white_balance", "Automatic white balance")
        self._settings = WhiteBalanceSettings.from_node(node)
        self._enabled = self._settings.enabled

    def prepare(self, image: Image.Image, context: ProcessingContext) -> None:
        settings = with_overrides(self._settings, context.overrides.get(self.name))
        context.data[self.name] = WhiteBalanceDecision(gains=self._detect(image, settings), method=settings.method)

    def execute(self, image: Image.Image, context: ProcessingContext) -> ProcessorResult:
        settings = with_overrides(self._settings, context.overrides.get(self.name))
        decision = context.data.get(self.name)

        if not isinstance(decision, WhiteBalanceDecision):
            decision = WhiteBalanceDecision(self._detect(image, settings), settings.method)

        strength = max(0.0, min(1.0, settings.strength))
        gains = np.array([1.0 + strength * (gain - 1.0) for gain in decision.gains], dtype="float32")
        pixels, alpha = to_rgb_array(image)

        return ProcessorResult(
            from_rgb_array(pixels.astype("float32") * gains, alpha), self._record(settings, decision, gains)
        )

    def validate_override(self, override) -> str | None:
        if not isinstance(override, WhiteBalanceOverride):
            return None

        if override.method is not None and override.method not in METHODS:
            return f"Unknown white balance method '{override.method}'."

        if override.strength is not None and (
            not math.isfinite(override.strength) or not 0.0 <= override.strength <= 1.0
        ):
            return "Strength must be between 0 and 1."

        for name, value in (("Temperature", override.temperature), ("Tint", override.tint)):
            if value is not None and (not math.isfinite(value) or abs(value) > 1):
                return f"{name} must be between -1 and 1."

        if override.analysis_max_dimension is not None and not 1 <= override.analysis_max_dimension <= 8192:
            return "The analysis size must be between 1 and 8192 px."

        return None

    def _detect(self, image: Image.Image, settings: WhiteBalanceSettings) -> tuple[float, float, float]:
        temperature = max(-1.0, min(1.0, settings.temperature))
        tint = max(-1.0, min(1.0, settings.tint))
        manual = np.array(
            [1.0 + 0.25 * temperature + 0.10 * tint, 1.0 - 0.10 * tint, 1.0 - 0.25 * temperature + 0.10 * tint],
            dtype="float32",
        )

        if settings.method != GRAY_WORLD:
            return tuple(float(gain) for gain in manual)

        sample, _ = to_rgb_array(analysis_copy(image, settings.analysis_max_dimension))
        values = sample.reshape(-1, 3).astype("float32")
        luminance = values.mean(axis=1)
        usable = values[(luminance > 8.0) & (luminance < 247.0)]

        if usable.size == 0:
            usable = values

        if usable.size == 0:
            return tuple(float(gain) for gain in manual)

        low, high = np.percentile(usable, [5, 95], axis=0)
        means = np.clip(usable, low, high).mean(axis=0)
        target = float(means.mean())
        detected = target / np.maximum(means, 1.0)

        return tuple(float(gain) for gain in np.clip(detected * manual, 0.5, 2.0))

    def _record(self, settings: WhiteBalanceSettings, decision: WhiteBalanceDecision, gains: np.ndarray) -> dict:
        return {
            "step": self.step,
            "summary": "Neutralized" if decision.method == GRAY_WORLD else "Temperature/tint",
            "details": {
                "Method": "Gray World" if decision.method == GRAY_WORLD else "Manual",
                "Gains": ", ".join(f"{gain:.2f}×" for gain in gains),
                "Strength": f"{settings.strength:.0%}",
                "Temperature": f"{settings.temperature:+.2f}",
                "Tint": f"{settings.tint:+.2f}",
            },
            "meta": {
                "method": decision.method,
                "gains": [round(float(gain), 4) for gain in decision.gains],
                "strength": settings.strength,
                "temperature": settings.temperature,
                "tint": settings.tint,
            },
        }
