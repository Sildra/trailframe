"""White balance processor: Gray World detection plus temperature/tint gains."""

from __future__ import annotations

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

    def __init__(self) -> None:
        super().__init__("White balance")
        self._settings = WhiteBalanceSettings()

    def configure_(self, config: Node) -> None:
        node = config.get_node("processing.white_balance", "Automatic white balance")
        self._settings = WhiteBalanceSettings.from_node(node)
        self._enabled = self._settings.enabled

    def prepare(self, image: Image.Image, context: ProcessingContext) -> None:
        context.data[self.name] = WhiteBalanceDecision(gains=self._detect(image), method=self._settings.method)

    def execute(self, image: Image.Image, context: ProcessingContext) -> ProcessorResult:
        decision = context.data.get(self.name)

        if not isinstance(decision, WhiteBalanceDecision):
            decision = WhiteBalanceDecision(self._detect(image), self._settings.method)

        strength = max(0.0, min(1.0, self._settings.strength))
        gains = np.array([1.0 + strength * (gain - 1.0) for gain in decision.gains], dtype="float32")
        pixels, alpha = to_rgb_array(image)

        return ProcessorResult(from_rgb_array(pixels.astype("float32") * gains, alpha), self._record(decision, gains))

    def _detect(self, image: Image.Image) -> tuple[float, float, float]:
        settings = self._settings
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

    def _record(self, decision: WhiteBalanceDecision, gains: np.ndarray) -> dict:
        return {
            "step": self.step,
            "summary": "Neutralized" if decision.method == GRAY_WORLD else "Temperature/tint",
            "details": {
                "Method": "Gray World" if decision.method == GRAY_WORLD else "Manual",
                "Gains": ", ".join(f"{gain:.2f}×" for gain in gains),
                "Strength": f"{self._settings.strength:.0%}",
                "Temperature": f"{self._settings.temperature:+.2f}",
                "Tint": f"{self._settings.tint:+.2f}",
            },
            "meta": {
                "method": decision.method,
                "gains": [round(float(gain), 4) for gain in decision.gains],
                "strength": self._settings.strength,
                "temperature": self._settings.temperature,
                "tint": self._settings.tint,
            },
        }
