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

from PIL import Image

from trailframe.log import get_logger
from trailframe.services.core.configuration_service import Node
from trailframe.services.photos.processing.tilt import CROP_MODE_NONE


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
    crop_mode: str = CROP_MODE_NONE
    # Analysis results shared between processors.
    data: dict[str, Any] = field(default_factory=dict)


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
