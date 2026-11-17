"""Rescale processor: size every alternative to its target longest edge."""

from __future__ import annotations

from PIL import Image

from trailframe.services.processors.processor import ProcessingContext, Processor, ProcessorResult


class RescaleProcessor(Processor):
    """Resizes the corrected image so its longest edge matches the target.

    The driver pre-downscales the source using the chain's scale hints, so this
    step usually only corrects the rounding of that estimate. An original
    smaller than the target is never upscaled.
    """

    step = "rescale"
    per_target = True

    def __init__(self) -> None:
        super().__init__("Rescale")

    def execute(self, image: Image.Image, context: ProcessingContext) -> ProcessorResult:
        target = context.target
        longest = max(image.size)

        if longest > target:
            image.thumbnail((target, target), Image.Resampling.LANCZOS)
        elif longest < target and max(context.source_size) >= target:
            ratio = target / longest
            size = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))
            image = image.resize(size, Image.Resampling.LANCZOS)

        return ProcessorResult(
            image,
            {
                "step": self.step,
                "summary": f"{image.width} × {image.height}",
                "details": {
                    "Target size": f"{target} px",
                    "Format": context.format.upper(),
                    "Quality": str(context.quality),
                },
                "meta": {},
            },
        )
