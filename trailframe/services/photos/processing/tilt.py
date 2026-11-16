"""Horizon/tilt detection and correction for processed alternatives.

The original archive is never touched: detection runs on a downscaled copy and
the correction is applied only to the derived alternatives.

The detector is pluggable: implement :class:`TiltDetector` and register it with
:func:`register_detector`, then select it with ``processing.tilt.method``. The
first implementation is the OpenCV Hough detector below; a future semantic
sky/ground segmentation detector can be added without touching the processing
service.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import ClassVar, Protocol

import cv2
import numpy as np
from PIL import Image

from trailframe.services.core.configuration_service import Node

CROP_MODE_MAXIMUM_RECTANGLE = "maximum_valid_rectangle"
CROP_MODE_NONE = "none"

DEFAULT_METHOD = "hough"
MANUAL_METHOD = "manual"


def _as_bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}

    return bool(value)


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
    auto_apply: bool = True
    crop_mode: str = CROP_MODE_MAXIMUM_RECTANGLE

    @classmethod
    def from_node(cls, node: Node) -> TiltSettings:
        """Read the settings from a configuration node, registering the defaults."""
        return cls(
            enabled=_as_bool(node.get_path_value("enabled", "Detect and correct a tilted horizon", cls.enabled)),
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
            auto_apply=_as_bool(
                node.get_path_value(
                    "auto_apply", "Rotate the alternatives when the estimate is trusted", cls.auto_apply
                )
            ),
            crop_mode=str(
                node.get_path_value("crop_mode", f"{CROP_MODE_MAXIMUM_RECTANGLE} or {CROP_MODE_NONE}", cls.crop_mode)
            ),
        )


@dataclass(frozen=True)
class TiltEstimate:
    """Result of a detector.

    ``angle`` is the correction angle in degrees, using the same sign
    convention as :meth:`PIL.Image.Image.rotate` (positive is counter-clockwise).
    ``confidence`` is in ``0..1`` and folds the agreement between supporting
    lines and the amount of line support found in the frame.

    ``line`` is the best supporting segment as normalized coordinates
    (``x1, y1, x2, y2`` in ``0..1`` of the analysis image), so the UI can draw
    the detected horizon. :attr:`reference_point` is its midpoint.
    """

    angle: float
    confidence: float
    method: str
    support: float = 0.0
    line: tuple[float, float, float, float] | None = None

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
    line support, so a single short edge cannot trigger a correction.
    """

    name: ClassVar[str] = "hough"

    def detect(self, image: Image.Image, settings: TiltSettings) -> TiltEstimate | None:
        analysis = _downscale(image, settings.analysis_max_dimension)
        gray = np.asarray(analysis.convert("L"), dtype=np.uint8)

        if gray.size == 0:
            return None

        width = gray.shape[1]
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

        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            length = math.hypot(float(x2 - x1), float(y2 - y1))

            if length < min_line_length:
                continue

            angle = _slope_angle(float(x1), float(y1), float(x2), float(y2))

            if abs(angle) > settings.max_detection_angle:
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
        height = gray.shape[0]

        return TiltEstimate(
            angle=angle,
            confidence=confidence,
            method=self.name,
            support=inlier_weight,
            line=_normalized_line(best[2:], width, height),
        )


def correct(image: Image.Image, angle: float, settings: TiltSettings) -> tuple[Image.Image, dict[str, int] | None]:
    """Rotate an image and optionally crop to the largest inscribed rectangle."""
    rotation = float(angle)

    if abs(rotation) < 1e-6:
        return image.copy(), None

    rotated = image.rotate(rotation, resample=Image.Resampling.BICUBIC, expand=True)

    if settings.crop_mode == CROP_MODE_NONE:
        return rotated, None

    width, height = largest_inscribed_rectangle(image.width, image.height, rotation)
    left = max(0, (rotated.width - width) // 2)
    top = max(0, (rotated.height - height) // 2)
    cropped = rotated.crop((left, top, left + width, top + height))

    return cropped, {"width": cropped.width, "height": cropped.height}


def largest_inscribed_rectangle(width: int, height: int, angle: float) -> tuple[int, int]:
    """Largest axis-aligned rectangle with no border, after rotating by ``angle``."""
    if width <= 0 or height <= 0:
        return max(1, width), max(1, height)

    radians = math.radians(abs(angle) % 180.0)

    if radians > math.pi / 2:
        radians = math.pi - radians

    sin_a = abs(math.sin(radians))
    cos_a = abs(math.cos(radians))

    if sin_a < 1e-9 or cos_a < 1e-9:
        return width, height

    width_is_longer = width >= height
    long_side, short_side = (width, height) if width_is_longer else (height, width)

    if short_side <= 2 * sin_a * cos_a * long_side or abs(sin_a - cos_a) < 1e-9:
        half = 0.5 * short_side
        rect_width, rect_height = (half / sin_a, half / cos_a) if width_is_longer else (half / cos_a, half / sin_a)
    else:
        cos_2a = cos_a * cos_a - sin_a * sin_a
        rect_width = (width * cos_a - height * sin_a) / cos_2a
        rect_height = (height * cos_a - width * sin_a) / cos_2a

    return (max(1, min(width, round(rect_width))), max(1, min(height, round(rect_height))))


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
