from __future__ import annotations

import math

import allure
import pytest
from PIL import Image, ImageDraw

from trailframe.services.core.configuration_service import Node
from trailframe.services.processors.crop_processor import CropProcessor, largest_inscribed_rectangle
from trailframe.services.processors.processor import CROP_MODE_MAXIMUM_RECTANGLE, CROP_MODE_NONE, ProcessingContext
from trailframe.services.processors.tilt_processor import (
    HoughTiltDetector,
    TiltEstimate,
    TiltOverride,
    TiltProcessor,
    TiltSettings,
    available_detectors,
    decide,
    detect_tilt,
    get_detector,
    register_detector,
)


def _tilted_line(angle: float, size: tuple[int, int] = (900, 600)) -> Image.Image:
    """An image whose content is rotated counter-clockwise by ``angle`` degrees."""
    image = Image.new("RGB", size, (245, 245, 245))
    draw = ImageDraw.Draw(image)
    left, right = 30, size[0] - 30
    width = right - left
    center = size[1] / 2
    draw.line((left, center, right, center - width * math.tan(math.radians(angle))), fill=(10, 10, 10), width=4)

    return image


def _two_line_image() -> Image.Image:
    """A strong tilted line at the top edge and a weaker central one."""
    image = Image.new("RGB", (900, 600), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    draw.line((0, 20, 900, 20 + 900 * math.tan(math.radians(6.0))), fill=(10, 10, 10), width=5)
    draw.line((200, 300, 700, 300 - 500 * math.tan(math.radians(2.0))), fill=(10, 10, 10), width=4)

    return image


def _estimate(angle: float, confidence: float) -> TiltEstimate:
    return TiltEstimate(angle=angle, confidence=confidence, method="hough")


def _corrected(
    image: Image.Image, settings: TiltSettings, *, angle: float | None = None
) -> tuple[Image.Image, dict | None]:
    """Run the tilt and crop processors on an image, like the driver does."""
    tilt = TiltProcessor()
    tilt._settings = settings
    tilt._enabled = settings.enabled
    context = ProcessingContext(source_size=image.size, working_size=image.size)

    if angle is not None:
        context.overrides["Tilt"] = TiltOverride(angle=angle)

    tilt.prepare(image, context)
    rotated = tilt.execute(image, context).image
    cropped = CropProcessor().execute(rotated, context)

    return cropped.image, cropped.step


class TestTilt:
    @allure.title("Detects the dominant near-horizontal angle and its sign")
    @pytest.mark.parametrize("angle", [2.0, -3.0])
    def test_hough_detects_tilt(self, angle):
        estimate = detect_tilt(_tilted_line(angle), TiltSettings())

        assert estimate is not None
        assert estimate.method == "hough"
        assert estimate.angle == pytest.approx(-angle, abs=0.3)
        assert estimate.confidence > 0.9
        assert estimate.line is not None
        assert 0 <= estimate.line[0] < estimate.line[2] <= 1
        assert 0 <= estimate.line[1] <= 1
        assert 0 <= estimate.line[3] <= 1

        reference = estimate.reference_point
        assert reference is not None
        assert reference[0] == pytest.approx((estimate.line[0] + estimate.line[2]) / 2)
        assert reference[1] == pytest.approx((estimate.line[1] + estimate.line[3]) / 2)

    @allure.title("The detector stores its supporting segments")
    def test_supporting_segments(self):
        estimate = detect_tilt(_tilted_line(2.0), TiltSettings())

        assert estimate is not None
        assert estimate.segments
        assert max(segment.weight for segment in estimate.segments) == pytest.approx(1.0)
        assert all(0 < segment.weight <= 1 for segment in estimate.segments)
        assert all(
            abs(segment.angle - estimate.angle) <= TiltSettings().inlier_tolerance for segment in estimate.segments
        )

        for segment in estimate.segments:
            x1, y1, x2, y2 = segment.line
            assert 0 <= x1 < x2 <= 1
            assert 0 <= y1 <= 1
            assert 0 <= y2 <= 1

        assert any(segment.line == estimate.line for segment in estimate.segments)

    @allure.title("Only lines near the image centre contribute to the estimate")
    def test_center_filter(self):
        image = _two_line_image()
        central = detect_tilt(image, TiltSettings())

        assert central is not None
        assert central.angle == pytest.approx(-2.0, abs=0.7)
        assert central.segments

        for segment in central.segments:
            x1, y1, x2, y2 = segment.line
            assert math.hypot((x1 + x2) / 2 - 0.5, (y1 + y2) / 2 - 0.5) <= 0.35 + 1e-6

        unrestricted = detect_tilt(image, TiltSettings(max_center_offset=1.0))

        assert unrestricted is not None
        assert unrestricted.angle == pytest.approx(6.0, abs=1.0)

    @allure.title("Correcting the estimate removes the tilt")
    def test_correction_removes_tilt(self):
        settings = TiltSettings()
        image = _tilted_line(2.0)
        estimate = detect_tilt(image, settings)

        assert estimate is not None

        corrected, crop = _corrected(image, settings, angle=estimate.angle)
        after = detect_tilt(corrected, settings)

        assert crop is not None
        assert corrected.width < image.width
        assert corrected.height < image.height
        assert after is not None
        assert after.angle == pytest.approx(0.0, abs=0.2)

    @allure.title("An image without lines has no estimate")
    def test_flat_image_has_no_estimate(self):
        assert detect_tilt(Image.new("RGB", (400, 300), (120, 120, 120)), TiltSettings()) is None

    @allure.title("Crop mode none keeps the expanded canvas")
    def test_crop_mode_none(self):
        image = _tilted_line(2.0)
        corrected, crop = _corrected(image, TiltSettings(crop_mode=CROP_MODE_NONE), angle=2.0)

        assert crop is None
        assert corrected.width > image.width
        assert corrected.height > image.height

    @allure.title("The largest inscribed rectangle stays inside the original")
    def test_largest_inscribed_rectangle(self):
        assert largest_inscribed_rectangle(900, 600, 0.0) == (900, 600)

        for size in ((900, 600), (600, 900), (1000, 1000)):
            for angle in (1.0, 3.0, 5.0, 45.0):
                width, height = largest_inscribed_rectangle(*size, angle)
                assert 0 < width <= size[0]
                assert 0 < height <= size[1]

        assert largest_inscribed_rectangle(900, 600, 5.0)[0] < 900

    @allure.title("The inscribed crop leaves no reflected or filled border")
    def test_inscribed_crop_avoids_borders(self):
        image = Image.new("RGB", (900, 600), (240, 240, 240))
        corrected, crop = _corrected(image, TiltSettings(), angle=3.0)

        assert crop is not None

        for point in (
            (0, 0),
            (corrected.width - 1, 0),
            (0, corrected.height - 1),
            (corrected.width - 1, corrected.height - 1),
        ):
            assert min(corrected.getpixel(point)) > 200

    @allure.title("An unknown detector yields no estimate")
    def test_unknown_detector(self):
        assert detect_tilt(_tilted_line(2.0), TiltSettings(method="missing")) is None
        assert get_detector("missing") is None

    @allure.title("A registered detector can be selected by name")
    def test_detector_registry(self):
        class FixedDetector:
            name = "fixed-test"

            def detect(self, image, settings):
                return TiltEstimate(angle=1.25, confidence=0.95, method=self.name)

        register_detector(FixedDetector())

        assert "fixed-test" in available_detectors()
        assert get_detector("FIXED-TEST") is not None

        estimate = detect_tilt(_tilted_line(2.0), TiltSettings(method="fixed-test"))

        assert estimate is not None
        assert estimate.angle == 1.25

    @allure.title("Settings read their defaults and the served values from the config node")
    def test_settings_from_node(self):
        node = Node("tilt")
        defaults = TiltSettings.from_node(node)

        assert defaults == TiltSettings()
        assert node.children["method"].has_value
        assert node.children["min_angle"].value == 0.3
        assert node.children["max_center_offset"].has_value

        node.get_node("enabled").set_value(False)
        node.get_node("min_confidence").set_value(0.75)
        node.get_node("max_center_offset").set_value(0.2)

        loaded = TiltSettings.from_node(node)

        assert loaded.enabled is False
        assert loaded.min_confidence == 0.75
        assert loaded.max_center_offset == 0.2
        assert loaded.crop_mode == CROP_MODE_MAXIMUM_RECTANGLE


class TestTiltPolicy:
    @allure.title("No estimate is never applied")
    def test_no_estimate(self):
        decision = decide(None, TiltSettings())

        assert decision.applied is False
        assert decision.reason == "no_estimate"

    @allure.title("Corrections below min_angle are ignored")
    def test_below_min_angle(self):
        decision = decide(_estimate(0.2, 1.0), TiltSettings())

        assert decision.applied is False
        assert decision.reason == "below_min_angle"

    @allure.title("A confident normal correction is applied")
    def test_normal_correction(self):
        decision = decide(_estimate(1.2, 0.7), TiltSettings())

        assert decision.applied is True
        assert decision.reason == "applied"

    @allure.title("A normal correction needs the normal confidence")
    def test_normal_low_confidence(self):
        decision = decide(_estimate(1.2, 0.5), TiltSettings())

        assert decision.applied is False
        assert decision.reason == "low_confidence"

    @allure.title("A large correction needs high confidence")
    def test_large_correction_needs_high_confidence(self):
        assert decide(_estimate(4.0, 0.7), TiltSettings()).applied is False
        assert decide(_estimate(4.0, 0.9), TiltSettings()).applied is True

    @allure.title("Corrections above the high-confidence limit are ignored")
    def test_above_max_angle(self):
        decision = decide(_estimate(6.0, 1.0), TiltSettings())

        assert decision.applied is False
        assert decision.reason == "above_max_angle"

    @allure.title("auto_apply false only reports the estimate")
    def test_auto_apply_disabled(self):
        decision = decide(_estimate(1.2, 1.0), TiltSettings(auto_apply=False))

        assert decision.applied is False
        assert decision.reason == "auto_apply_disabled"
        assert decision.estimate is not None

    @allure.title("The Hough detector is registered by default")
    def test_hough_registered(self):
        assert isinstance(get_detector("hough"), HoughTiltDetector)
