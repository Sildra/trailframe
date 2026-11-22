"""Crop processor: trim the borders a tilt correction introduces."""

from __future__ import annotations

import math

from PIL import Image

from trailframe.services.processors.processor import CROP_MODE_NONE, ProcessingContext, Processor, ProcessorResult


class CropProcessor(Processor):
    """Crops the rotated image to the largest rectangle without empty borders.

    The rotation itself is the tilt processor's job; this step only consumes the
    angle it published. Without a correction, or with ``crop_mode: none``, the
    image is passed through and no step is recorded.
    """

    step = "crop"

    def __init__(self) -> None:
        super().__init__("Crop")

    def scale(self, context: ProcessingContext) -> float:
        """How much the inscribed rectangle shrinks the rotated canvas."""
        width, height = context.source_size
        angle = context.angle

        if abs(angle) < 1e-6 or context.crop_mode == CROP_MODE_NONE or width <= 0 or height <= 0:
            return 1.0

        radians = math.radians(abs(angle))
        sin_a, cos_a = abs(math.sin(radians)), abs(math.cos(radians))
        rotated = max(width * cos_a + height * sin_a, width * sin_a + height * cos_a)
        cropped = max(largest_inscribed_rectangle(width, height, angle))

        return cropped / rotated

    def execute(self, image: Image.Image, context: ProcessingContext) -> ProcessorResult:
        if abs(context.angle) < 1e-6 or context.crop_mode == CROP_MODE_NONE:
            return ProcessorResult(image)

        width, height = largest_inscribed_rectangle(*context.working_size, context.angle)
        width = min(width, image.width)
        height = min(height, image.height)

        left = max(0, (image.width - width) // 2)
        top = max(0, (image.height - height) // 2)
        cropped = image.crop((left, top, left + width, top + height))

        return ProcessorResult(
            cropped,
            {
                "step": self.step,
                "summary": "Borders trimmed",
                "details": {"Crop mode": context.crop_mode},
                "meta": {"size": {"width": width, "height": height}},
            },
        )

    def ran(self, steps: list[dict]) -> bool:
        if super().ran(steps):
            return True

        tilt = next((step for step in steps if isinstance(step, dict) and step.get("step") == "tilt"), None)

        if tilt is None:
            # No tilt processor ran, so there was nothing to crop.
            return True

        meta = tilt.get("meta")

        if not isinstance(meta, dict):
            return True

        # Nothing to crop when the horizon was not corrected, or when the
        # correction deliberately keeps the expanded canvas.
        return not meta.get("applied") or meta.get("crop_mode") == CROP_MODE_NONE


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
