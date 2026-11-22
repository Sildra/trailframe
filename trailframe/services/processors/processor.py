"""Base class and shared state for the photo preprocessing steps.

A processor is one step of the chain applied to a decoded original before it is
written as an alternative. Processors mirror the scanners: they are configured
once, decide whether they take part in a photo, and record what they did in the
`processing` provenance. The driver (`ProcessingService`) only decodes the
original, runs the chain and writes the files; it knows nothing about the
individual steps.

A processor may analyse the source image once (`prepare`) and then transform it
for every target size (`execute`), so an expensive detection such as the horizon
estimate is not repeated per target. `scale` reports how much a processor shrinks
the longest edge, which lets the driver pre-downscale the source just enough for
the written file to still have the requested longest edge.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image

from trailframe.log import get_logger
from trailframe.services.core.configuration_service import Node

CROP_MODE_MAXIMUM_RECTANGLE = "maximum_valid_rectangle"
CROP_MODE_NONE = "none"
CROP_MODES = frozenset({CROP_MODE_MAXIMUM_RECTANGLE, CROP_MODE_NONE})


@dataclass
class ProcessingContext:
    """Mutable state shared by the processors of one photo, in chain order."""

    # Target size of the current pass (longest edge, px).
    target: int = 0
    # Size of the decoded, EXIF-transposed original.
    source_size: tuple[int, int] = (0, 0)
    # Size of the image handed to the chain for the current target.
    working_size: tuple[int, int] = (0, 0)
    # Encoding settings of the alternatives.
    format: str = "webp"
    quality: int = 90
    # Per-run overrides, keyed by processor name (see `validate_override`).
    overrides: dict[str, Any] = field(default_factory=dict)
    # Published by the tilt processor and consumed by the crop processor.
    angle: float = 0.0
    crop_mode: str = CROP_MODE_MAXIMUM_RECTANGLE
    # Analysis results shared between processors.
    data: dict[str, Any] = field(default_factory=dict)


def as_bool(value: object) -> bool:
    """Interpret YAML/JSON booleans and the usual textual spellings."""
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}

    return bool(value)


def to_rgb_array(image: Image.Image) -> tuple[np.ndarray, Image.Image | None]:
    """Pixels of an image as an RGB array, keeping any alpha channel aside."""
    alpha = image.getchannel("A") if "A" in image.getbands() else None

    return np.asarray(image.convert("RGB"), dtype=np.uint8), alpha


def from_rgb_array(array: np.ndarray, alpha: Image.Image | None = None) -> Image.Image:
    """Build an image back from an RGB array, restoring the original alpha."""
    pixels = np.ascontiguousarray(np.clip(np.nan_to_num(array), 0, 255).astype(np.uint8))
    result = Image.fromarray(pixels, "RGB")

    if alpha is not None:
        result.putalpha(alpha)

    return result


def analysis_copy(image: Image.Image, max_dimension: int) -> Image.Image:
    """A downscaled copy for per-photo analysis that does not need full pixels."""
    longest = max(image.size)

    if max_dimension <= 0 or longest <= max_dimension:
        return image

    ratio = max_dimension / longest
    size = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))

    return image.resize(size, Image.Resampling.BILINEAR)


@dataclass
class ProcessorResult:
    """The transformed image plus the provenance entry describing the step."""

    image: Image.Image
    step: dict | None = None


class Processor(ABC):
    """One step of the preprocessing chain."""

    # Provenance step name this processor records.
    step: str = "processing"
    # Whether the step is recorded once per photo or once per target size.
    per_target: bool = False

    def __init__(self, name: str) -> None:
        self.name = name
        self._enabled = True

    @staticmethod
    def _log(message: str, level: int = logging.INFO) -> None:
        get_logger().log(level, message)

    def configure(self, config: Node) -> None:
        self.configure_(config)

    def configure_(self, config: Node) -> None:
        pass

    def accept(self, context: ProcessingContext | None = None) -> bool:
        """Whether the processor takes part in this photo."""
        return self._enabled

    def prepare(self, image: Image.Image, context: ProcessingContext) -> None:
        """Analyse the source image once, before the per-target passes."""

    def scale(self, context: ProcessingContext) -> float:
        """Longest-edge ratio of this processor's output to its input."""
        return 1.0

    @abstractmethod
    def execute(self, image: Image.Image, context: ProcessingContext) -> ProcessorResult:
        """Transform the image of one target pass."""

    def validate_override(self, override: Any) -> str | None:
        """Return a problem with a per-run override, or None when it is valid."""
        return None

    def ran(self, steps: list[dict]) -> bool:
        """Whether the recorded provenance shows this processor already ran."""
        return any(isinstance(step, dict) and step.get("step") == self.step for step in steps)
