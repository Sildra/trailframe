"""Exposure processor: exposure compensation and gamma in linear-ish RGB."""

from __future__ import annotations

import math
from dataclasses import dataclass

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
class ExposureSettings:
    """Settings of ``processing.exposure``."""

    enabled: bool = False
    exposure: float = 0.0
    gamma: float = 1.0

    @classmethod
    def from_node(cls, node: Node) -> ExposureSettings:
        return cls(
            enabled=as_bool(node.get_path_value("enabled", "Apply exposure compensation and gamma", cls.enabled)),
            exposure=float(node.get_path_value("exposure", "Exposure compensation in stops (EV)", cls.exposure)),
            gamma=float(node.get_path_value("gamma", "Tone curve gamma (1 keeps the midtones)", cls.gamma)),
        )


@dataclass(frozen=True)
class ExposureOverride:
    """Per-photo override of the exposure step."""

    enabled: bool | None = None
    exposure: float | None = None
    gamma: float | None = None


class ExposureProcessor(Processor):
    """Scales brightness by a stop-based gain, then applies a gamma curve.

    Exposure is linear in light, so it is applied before the tone processors.
    Gamma above 1 lifts the midtones; values below 1 deepen them. No detection is
    involved: both settings are explicit and recorded in the provenance step.
    """

    step = "exposure"
    overridable = True

    def __init__(self) -> None:
        super().__init__("Exposure")
        self._settings = ExposureSettings()

    def configure_(self, config: Node) -> None:
        node = config.get_node("processing.exposure", "Exposure compensation")
        self._settings = ExposureSettings.from_node(node)
        self._enabled = self._settings.enabled

    def execute(self, image: Image.Image, context: ProcessingContext) -> ProcessorResult:
        settings = with_overrides(self._settings, context.overrides.get(self.name))
        pixels, alpha = to_rgb_array(image)
        values = pixels.astype("float32") / 255.0

        gain = 2.0 ** max(-6.0, min(6.0, settings.exposure))
        values *= gain

        gamma = max(0.2, min(5.0, settings.gamma))

        if abs(gamma - 1.0) > 1e-6:
            values = values ** (1.0 / gamma)

        result = from_rgb_array(values * 255.0, alpha)

        return ProcessorResult(result, self._record(settings, gain, gamma))

    def validate_override(self, override) -> str | None:
        if not isinstance(override, ExposureOverride):
            return None

        if override.exposure is not None and (not math.isfinite(override.exposure) or abs(override.exposure) > 6):
            return "Exposure must be between -6 and +6 EV."

        if override.gamma is not None and (not math.isfinite(override.gamma) or not 0.2 <= override.gamma <= 5):
            return "Gamma must be between 0.2 and 5."

        return None

    def _record(self, settings: ExposureSettings, gain: float, gamma: float) -> dict:
        return {
            "step": self.step,
            "summary": f"{gain:g}× · γ {gamma:g}",
            "details": {"Exposure": f"{settings.exposure:+.2f} EV", "Gamma": f"{settings.gamma:.2f}", "Applied": "Yes"},
            "meta": {"exposure": settings.exposure, "gamma": settings.gamma},
        }
