from __future__ import annotations

import allure
from PIL import Image

from trailframe.services.processors import PROCESSOR_DEFINITIONS
from trailframe.services.processors.processor import ProcessingContext


def _processor(name: str):
    from trailframe.services.photos.processing_service import ProcessingService

    return next(processor for processor in ProcessingService._processors if processor.name == name)


class TestProcessorChain:
    @allure.title("The chain runs tilt, then crop, then rescale")
    def test_chain_order(self, app):
        from trailframe.services.photos.processing_service import ProcessingService

        assert [definition.name for definition in PROCESSOR_DEFINITIONS] == ["Tilt", "Crop", "Rescale"]
        assert [processor.name for processor in ProcessingService._processors] == ["Tilt", "Crop", "Rescale"]
        assert [processor.step for processor in ProcessingService._processors] == ["tilt", "crop", "rescale"]

    @allure.title("A crop step is only expected when the horizon correction was applied")
    def test_crop_run_state(self, app):
        crop = _processor("Crop")
        rescale = {"step": "rescale", "summary": "1080 × 720", "details": {}, "meta": {}}
        not_applied = {"step": "tilt", "meta": {"applied": False, "crop_mode": "maximum_valid_rectangle"}}
        applied = {"step": "tilt", "meta": {"applied": True, "crop_mode": "maximum_valid_rectangle"}}
        expanded = {"step": "tilt", "meta": {"applied": True, "crop_mode": "none"}}

        assert crop.ran([not_applied, rescale]) is True
        assert crop.ran([applied, rescale]) is False
        assert crop.ran([expanded, rescale]) is True
        assert crop.ran([rescale]) is True


class TestCropProcessor:
    @allure.title("The crop step is recorded only when the borders were trimmed")
    def test_crop_records_only_when_applied(self, app):
        crop = _processor("Crop")
        image = Image.new("RGB", (120, 80), (200, 200, 200))
        context = ProcessingContext(
            source_size=image.size, working_size=image.size, angle=0.0, crop_mode="maximum_valid_rectangle"
        )

        assert crop.execute(image, context).step is None

        context.angle = 2.0
        rotated = image.rotate(2.0, resample=Image.Resampling.BICUBIC, expand=True)
        result = crop.execute(rotated, context)

        assert result.step is not None
        assert result.step["step"] == "crop"
        assert result.image.width < rotated.width
        assert result.image.height < rotated.height

    @allure.title("Crop mode none keeps the expanded canvas")
    def test_crop_mode_none(self, app):
        crop = _processor("Crop")
        image = Image.new("RGB", (120, 80), (200, 200, 200))
        context = ProcessingContext(source_size=image.size, working_size=image.size, angle=2.0, crop_mode="none")

        assert crop.execute(image, context).step is None


class TestRescaleProcessor:
    @allure.title("Rescale keeps the target as the longest edge")
    def test_rescale_to_target(self, app):
        rescale = _processor("Rescale")
        image = Image.new("RGB", (4000, 3000), (10, 20, 30))
        context = ProcessingContext(source_size=image.size, target=1080)

        result = rescale.execute(image, context)

        assert max(result.image.size) == 1080
        assert result.step is not None
        assert result.step["summary"] == f"{result.image.width} × {result.image.height}"
        assert result.step["details"]["Target size"] == "1080 px"

    @allure.title("Rescale never upscales an original smaller than the target")
    def test_rescale_does_not_upscale(self, app):
        rescale = _processor("Rescale")
        image = Image.new("RGB", (320, 240), (10, 20, 30))
        context = ProcessingContext(source_size=image.size, target=1080)

        assert max(rescale.execute(image, context).image.size) == 320
