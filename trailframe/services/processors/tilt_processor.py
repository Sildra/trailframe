"""Tilt processor: detect a tilted horizon and level the alternatives."""

from __future__ import annotations

import logging
import math

from PIL import Image

from trailframe.services.core.configuration_service import Node
from trailframe.services.photos.processing.tilt import (
    CROP_MODES,
    MANUAL_METHOD,
    TiltDecision,
    TiltEstimate,
    TiltOverride,
    TiltSettings,
    decide,
    detect_tilt,
    get_detector,
)
from trailframe.services.processors.processor import ProcessingContext, Processor, ProcessorResult

MAX_MANUAL_ANGLE = 45.0

_REASON_TEXT = {
    "no_estimate": "no estimate",
    "below_min_angle": "below minimum angle",
    "above_max_angle": "above maximum angle",
    "low_confidence": "low confidence",
    "auto_apply_disabled": "auto-apply disabled",
    "disabled": "disabled",
    "failed": "failed",
}


class TiltProcessor(Processor):
    """Detects the dominant horizon and rotates the alternatives to level it.

    The estimate is computed once on a downscaled copy of the source. The
    correction is applied per target; the crop processor trims the borders the
    rotation introduces.
    """

    step = "tilt"

    def __init__(self) -> None:
        super().__init__("Tilt")
        self._settings = TiltSettings()

    def configure_(self, config: Node) -> None:
        node = config.get_node("processing.tilt", "Automatic horizon straightening")
        self._settings = TiltSettings.from_node(node)
        self._enabled = self._settings.enabled

        if self._enabled and get_detector(self._settings.method) is None:
            self._log(
                f"unknown tilt detector '{self._settings.method}', horizon correction is disabled", logging.WARNING
            )

    def prepare(self, image: Image.Image, context: ProcessingContext) -> None:
        override = context.overrides.get(self.name)
        decision = self._decision(image, override)

        context.angle = decision.estimate.angle if decision.applied and decision.estimate is not None else 0.0
        context.crop_mode = (
            override.crop_mode
            if isinstance(override, TiltOverride) and override.crop_mode
            else self._settings.crop_mode
        )
        context.data[self.name] = decision

    def scale(self, context: ProcessingContext) -> float:
        """How much the expanded canvas grows the longest edge."""
        width, height = context.source_size
        angle = context.angle

        if abs(angle) < 1e-6 or width <= 0 or height <= 0:
            return 1.0

        radians = math.radians(abs(angle))
        sin_a, cos_a = abs(math.sin(radians)), abs(math.cos(radians))
        rotated = max(width * cos_a + height * sin_a, width * sin_a + height * cos_a)

        return rotated / max(width, height)

    def execute(self, image: Image.Image, context: ProcessingContext) -> ProcessorResult:
        decision = context.data.get(self.name)

        if isinstance(decision, TiltDecision) and decision.applied and decision.estimate is not None:
            image = image.rotate(decision.estimate.angle, resample=Image.Resampling.BICUBIC, expand=True)

        return ProcessorResult(image, self._record(decision, context))

    def validate_override(self, override) -> str | None:
        if not isinstance(override, TiltOverride):
            return None

        if override.angle is not None and (not math.isfinite(override.angle) or abs(override.angle) > MAX_MANUAL_ANGLE):
            return f"The manual angle must be within ±{MAX_MANUAL_ANGLE:g}°"

        if override.crop_mode is not None and override.crop_mode not in CROP_MODES:
            return f"Unknown crop mode '{override.crop_mode}'"

        return None

    def _decision(self, image: Image.Image, override) -> TiltDecision:
        if isinstance(override, TiltOverride):
            if override.angle is not None:
                estimate = TiltEstimate(angle=override.angle, confidence=1.0, method=MANUAL_METHOD)

                return TiltDecision(estimate, True, "manual")

            if override.enabled is False:
                return TiltDecision(None, False, "disabled")

        try:
            estimate = detect_tilt(image, self._settings)
        except Exception as exception:  # noqa: BLE001
            self._log(f"tilt detection failed: {exception}", logging.WARNING)

            return TiltDecision(None, False, "failed")

        return decide(estimate, self._settings)

    def _record(self, decision, context: ProcessingContext) -> dict:
        details = {
            "Detection method": self._settings.method,
            "Applied": "No",
            "Reason": _reason_text(decision.reason if decision is not None else "no_estimate"),
        }
        meta: dict = {"applied": False, "crop_mode": context.crop_mode}
        summary = "Not applied"
        estimate = decision.estimate if decision is not None else None

        if estimate is not None:
            details = {
                "Detection method": estimate.method,
                "Confidence": f"{estimate.confidence:.0%}",
                "Applied": "Yes" if decision.applied else "No",
            }
            meta["applied"] = decision.applied
            summary = _format_angle(estimate.angle)
            reference = estimate.reference_point

            if not decision.applied:
                details["Reason"] = _reason_text(decision.reason)

            if reference is not None:
                details["Reference point"] = f"{reference[0]:.1%}, {reference[1]:.1%}"
                meta["reference_point"] = {"x": round(reference[0], 4), "y": round(reference[1], 4)}

            if estimate.line is not None:
                meta["line"] = {
                    "x1": round(estimate.line[0], 4),
                    "y1": round(estimate.line[1], 4),
                    "x2": round(estimate.line[2], 4),
                    "y2": round(estimate.line[3], 4),
                }

        return {"step": self.step, "summary": summary, "details": details, "meta": meta}


def _reason_text(reason: str) -> str:
    return _REASON_TEXT.get(reason, reason.replace("_", " "))


def _format_angle(angle: float) -> str:
    rounded = round(float(angle), 2)

    if rounded == 0:
        rounded = 0.0

    return f"{rounded:+.2f}°"
