"""Tilt processor: horizon detection, decision, rotation and provenance.

Everything about the correction lives here: the pluggable detector, the
conservative decision policy, the rotation applied to each alternative and the
`tilt` provenance step. The original archive is never touched; detection runs on
a downscaled copy and the correction is applied only to derived alternatives.

Implement :class:`TiltDetector`, register it with :func:`register_detector` and
select it with ``processing.tilt.method`` to replace the Hough detector.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import ClassVar, Protocol

import cv2
import numpy as np
from PIL import Image

from trailframe.services.core.configuration_service import Node
from trailframe.services.processors.processor import (
    CROP_MODE_MAXIMUM_RECTANGLE,
    CROP_MODES,
    ProcessingContext,
    Processor,
    ProcessorResult,
    as_bool,
)

MAX_MANUAL_ANGLE = 45.0
MAX_STORED_SEGMENTS = 64

DEFAULT_METHOD = "hough"
MANUAL_METHOD = "manual"

_REASON_TEXT = {
    "no_estimate": "no estimate",
    "below_min_angle": "below minimum angle",
    "above_max_angle": "above maximum angle",
    "low_confidence": "low confidence",
    "auto_apply_disabled": "auto-apply disabled",
    "disabled": "disabled",
    "failed": "failed",
}


@dataclass(frozen=True)
class TiltSettings:
    """Configuration of the tilt step (``processing.tilt`` in config.yaml)."""

    enabled: bool = True
    method: str = DEFAULT_METHOD
    analysis_max_dimension: int = 1024
    min_angle: float = 0.3
    max_angle: float = 3.0
    high_confidence_max_angle: float = 5.0
    min_confidence: float = 0.7
    high_confidence: float = 0.9
    max_detection_angle: float = 12.0
    min_line_length_ratio: float = 0.08
    inlier_tolerance: float = 1.5
    max_center_offset: float = 0.35
    auto_apply: bool = True
    crop_mode: str = CROP_MODE_MAXIMUM_RECTANGLE

    @classmethod
    def from_node(cls, node: Node) -> TiltSettings:
        """Read the settings from a configuration node, registering the defaults."""
        return cls(
            enabled=as_bool(node.get_path_value("enabled", "Detect and correct a tilted horizon", cls.enabled)),
            method=str(node.get_path_value("method", "Detector: hough", cls.method)).lower(),
            analysis_max_dimension=int(
                node.get_path_value(
                    "analysis_max_dimension", "Longest edge used for detection, in pixels", cls.analysis_max_dimension
                )
            ),
            min_angle=float(
                node.get_path_value("min_angle", "Ignore corrections below this angle (degrees)", cls.min_angle)
            ),
            max_angle=float(
                node.get_path_value("max_angle", "Maximum correction at normal confidence (degrees)", cls.max_angle)
            ),
            high_confidence_max_angle=float(
                node.get_path_value(
                    "high_confidence_max_angle",
                    "Maximum correction at high confidence (degrees)",
                    cls.high_confidence_max_angle,
                )
            ),
            min_confidence=float(
                node.get_path_value("min_confidence", "Confidence required up to max_angle", cls.min_confidence)
            ),
            high_confidence=float(
                node.get_path_value("high_confidence", "Confidence required above max_angle", cls.high_confidence)
            ),
            max_detection_angle=float(
                node.get_path_value(
                    "max_detection_angle", "Ignore lines steeper than this (degrees)", cls.max_detection_angle
                )
            ),
            min_line_length_ratio=float(
                node.get_path_value(
                    "min_line_length_ratio",
                    "Minimum line length as a fraction of the short edge",
                    cls.min_line_length_ratio,
                )
            ),
            inlier_tolerance=float(
                node.get_path_value(
                    "inlier_tolerance", "Angle tolerance for inlier lines (degrees)", cls.inlier_tolerance
                )
            ),
            max_center_offset=float(
                node.get_path_value(
                    "max_center_offset",
                    "Maximum normalized distance of a detected line midpoint from the image centre (1 disables)",
                    cls.max_center_offset,
                )
            ),
            auto_apply=as_bool(
                node.get_path_value(
                    "auto_apply", "Rotate the alternatives when the estimate is trusted", cls.auto_apply
                )
            ),
            crop_mode=str(node.get_path_value("crop_mode", "maximum_valid_rectangle or none", cls.crop_mode)),
        )


@dataclass(frozen=True)
class TiltSegment:
    """A supporting Hough segment in normalized image coordinates.

    ``weight`` is relative to the strongest supporting segment (0..1), so the
    frontend can render faint lines for weak support and a strong primary line.
    """

    line: tuple[float, float, float, float]
    angle: float
    weight: float


@dataclass(frozen=True)
class TiltEstimate:
    """Result of a detector.

    ``angle`` is the correction angle in degrees, using the same sign
    convention as :meth:`PIL.Image.Image.rotate` (positive is counter-clockwise).
    ``confidence`` is in ``0..1`` and folds the agreement between supporting
    lines and the amount of line support found in the frame.

    ``line`` is the best supporting segment as normalized coordinates
    (``x1, y1, x2, y2`` in ``0..1`` of the analysis image), so the UI can draw
    the detected horizon. :attr:`reference_point` is its midpoint. ``segments``
    keeps the other inliers so the provenance can show what the estimate used.
    """

    angle: float
    confidence: float
    method: str
    support: float = 0.0
    line: tuple[float, float, float, float] | None = None
    segments: tuple[TiltSegment, ...] = ()

    @property
    def reference_point(self) -> tuple[float, float] | None:
        """Normalized midpoint of the supporting line."""
        if self.line is None:
            return None

        x1, y1, x2, y2 = self.line

        return (x1 + x2) / 2.0, (y1 + y2) / 2.0


@dataclass(frozen=True)
class TiltDecision:
    """Whether an estimate may be applied, and why."""

    estimate: TiltEstimate | None
    applied: bool
    reason: str


@dataclass(frozen=True)
class TiltOverride:
    """Per-photo override of the configured tilt step.

    ``enabled=False`` disables correction for one run, ``angle`` forces a manual
    rotation and skips detection, and ``crop_mode`` overrides the configured crop.
    """

    enabled: bool | None = None
    angle: float | None = None
    crop_mode: str | None = None


class TiltDetector(Protocol):
    """A pluggable tilt detector."""

    name: ClassVar[str]

    def detect(self, image: Image.Image, settings: TiltSettings) -> TiltEstimate | None: ...


_DETECTORS: dict[str, TiltDetector] = {}


def register_detector(detector: type[TiltDetector] | TiltDetector) -> type[TiltDetector] | TiltDetector:
    """Register a detector class or instance under its ``name``."""
    instance = detector() if isinstance(detector, type) else detector
    _DETECTORS[instance.name.lower()] = instance

    return detector


def get_detector(name: str) -> TiltDetector | None:
    return _DETECTORS.get((name or "").lower())


def available_detectors() -> list[str]:
    return sorted(_DETECTORS)


def detect_tilt(image: Image.Image, settings: TiltSettings) -> TiltEstimate | None:
    """Run the configured detector, returning None when it cannot estimate."""
    detector = get_detector(settings.method)

    if detector is None:
        return None

    return detector.detect(image, settings)


def decide(estimate: TiltEstimate | None, settings: TiltSettings) -> TiltDecision:
    """Apply the conservative confidence policy to an estimate."""
    if estimate is None:
        return TiltDecision(None, False, "no_estimate")

    if not settings.auto_apply:
        return TiltDecision(estimate, False, "auto_apply_disabled")

    angle = abs(estimate.angle)
    high_confidence_max_angle = max(settings.max_angle, settings.high_confidence_max_angle)

    if angle < settings.min_angle:
        return TiltDecision(estimate, False, "below_min_angle")

    if angle > high_confidence_max_angle:
        return TiltDecision(estimate, False, "above_max_angle")

    required = settings.min_confidence if angle <= settings.max_angle else settings.high_confidence

    if estimate.confidence < required:
        return TiltDecision(estimate, False, "low_confidence")

    return TiltDecision(estimate, True, "applied")


@register_detector
class HoughTiltDetector:
    """Near-horizontal line detection with Canny + HoughLinesP.

    Near-horizontal segments are weighted by length, the dominant angle is the
    weighted median, and the estimate is refined on the inliers. Confidence
    combines the share of line length supporting the angle with the absolute
    line support, so a single short edge cannot trigger a correction. Segments
    whose midpoint is too far from the image centre are ignored, keeping edges
    at the frame border from dominating the estimate.
    """

    name: ClassVar[str] = "hough"

    def detect(self, image: Image.Image, settings: TiltSettings) -> TiltEstimate | None:
        analysis = _downscale(image, settings.analysis_max_dimension)
        gray = np.asarray(analysis.convert("L"), dtype=np.uint8)

        if gray.size == 0:
            return None

        width = gray.shape[1]
        height = gray.shape[0]
        short_edge = min(gray.shape[:2])
        min_line_length = max(8, int(short_edge * max(0.0, settings.min_line_length_ratio)))

        if short_edge < 16 or min_line_length >= short_edge:
            return None

        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(
            edges,
            1,
            np.pi / 180,
            threshold=max(20, min_line_length // 2),
            minLineLength=min_line_length,
            maxLineGap=max(4, min_line_length // 4),
        )

        if lines is None:
            return None

        angles: list[float] = []
        weights: list[float] = []
        segments: list[tuple[float, float, float, float, float, float]] = []
        max_center_offset = max(0.0, float(settings.max_center_offset))

        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            length = math.hypot(float(x2 - x1), float(y2 - y1))

            if length < min_line_length:
                continue

            angle = _slope_angle(float(x1), float(y1), float(x2), float(y2))

            if abs(angle) > settings.max_detection_angle:
                continue

            midpoint_x = (float(x1) + float(x2)) / (2.0 * width)
            midpoint_y = (float(y1) + float(y2)) / (2.0 * height)

            if math.hypot(midpoint_x - 0.5, midpoint_y - 0.5) > max_center_offset:
                continue

            angles.append(angle)
            weights.append(length)
            segments.append((angle, length, float(x1), float(y1), float(x2), float(y2)))

        if not angles:
            return None

        median = _weighted_median(angles, weights)
        tolerance = max(0.1, settings.inlier_tolerance)
        inliers = [
            (angle, weight, x1, y1, x2, y2)
            for angle, weight, x1, y1, x2, y2 in segments
            if abs(angle - median) <= tolerance
        ]

        if not inliers:
            return None

        total_weight = sum(weights)
        inlier_weight = sum(inlier[1] for inlier in inliers)
        angle = sum(item[0] * item[1] for item in inliers) / inlier_weight
        best = max(inliers, key=lambda item: item[1])

        agreement = inlier_weight / total_weight if total_weight > 0 else 0.0
        support = 1.0 - math.exp(-inlier_weight / max(1.0, 0.20 * width))
        confidence = max(0.0, min(1.0, agreement * support))
        strongest = max((inlier[1] for inlier in inliers), default=1.0)
        supporting = sorted(
            (
                TiltSegment(
                    line=_normalized_line((x1, y1, x2, y2), width, height),
                    angle=angle,
                    weight=min(1.0, weight / strongest),
                )
                for angle, weight, x1, y1, x2, y2 in inliers
            ),
            key=lambda item: item.weight,
            reverse=True,
        )[:MAX_STORED_SEGMENTS]

        return TiltEstimate(
            angle=angle,
            confidence=confidence,
            method=self.name,
            support=inlier_weight,
            line=_normalized_line(best[2:], width, height),
            segments=tuple(supporting),
        )


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

            if estimate.segments:
                details["Supporting lines"] = str(len(estimate.segments))
                meta["segments"] = [
                    {
                        "x1": round(segment.line[0], 4),
                        "y1": round(segment.line[1], 4),
                        "x2": round(segment.line[2], 4),
                        "y2": round(segment.line[3], 4),
                        "angle": round(segment.angle, 2),
                        "weight": round(segment.weight, 3),
                    }
                    for segment in estimate.segments
                ]

        return {"step": self.step, "summary": summary, "details": details, "meta": meta}


def _reason_text(reason: str) -> str:
    return _REASON_TEXT.get(reason, reason.replace("_", " "))


def _format_angle(angle: float) -> str:
    rounded = round(float(angle), 2)

    if rounded == 0:
        rounded = 0.0

    return f"{rounded:+.2f}°"


def _downscale(image: Image.Image, max_dimension: int) -> Image.Image:
    longest = max(image.size)

    if max_dimension <= 0 or longest <= max_dimension:
        return image

    ratio = max_dimension / longest
    size = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))

    return image.resize(size, Image.Resampling.BILINEAR)


def _slope_angle(x1: float, y1: float, x2: float, y2: float) -> float:
    """Slope in degrees, normalized to (-90, 90] with screen coordinates (y down)."""
    angle = math.degrees(math.atan2(y2 - y1, x2 - x1))

    return (angle + 90.0) % 180.0 - 90.0


def _weighted_median(values: list[float], weights: list[float]) -> float:
    pairs = sorted(zip(values, weights))
    half = sum(weights) / 2.0
    cumulative = 0.0

    for value, weight in pairs:
        cumulative += weight

        if cumulative >= half:
            return value

    return pairs[-1][0]


def _normalized_line(
    segment: tuple[float, float, float, float], width: int, height: int
) -> tuple[float, float, float, float]:
    """Normalize a segment to ``0..1`` of the image, ordered left to right."""
    x1, y1, x2, y2 = segment

    if x2 < x1:
        x1, y1, x2, y2 = x2, y2, x1, y1

    return (
        max(0.0, min(1.0, x1 / width)),
        max(0.0, min(1.0, y1 / height)),
        max(0.0, min(1.0, x2 / width)),
        max(0.0, min(1.0, y2 / height)),
    )
