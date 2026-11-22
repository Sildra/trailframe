from __future__ import annotations

import allure
import numpy as np
from PIL import Image

from trailframe.services.core.configuration_service import Node
from trailframe.services.processors.contrast_processor import ContrastProcessor, ContrastSettings
from trailframe.services.processors.exposure_processor import ExposureProcessor, ExposureSettings
from trailframe.services.processors.local_contrast_processor import LocalContrastProcessor, LocalContrastSettings
from trailframe.services.processors.noise_reduction_processor import NoiseReductionProcessor, NoiseReductionSettings
from trailframe.services.processors.processor import ProcessingContext
from trailframe.services.processors.sharpening_processor import SharpeningProcessor, SharpeningSettings
from trailframe.services.processors.vibrance_processor import VibranceProcessor, VibranceSettings
from trailframe.services.processors.white_balance_processor import WhiteBalanceProcessor, WhiteBalanceSettings


def _configured(processor_class, key: str, **values):
    node = Node("root")
    settings = node.get_node(f"processing.{key}")

    for name, value in values.items():
        settings.get_node(name).set_value(value)

    processor = processor_class()
    processor.configure(node)

    return processor


def _solid(color: tuple[int, int, int], size: tuple[int, int] = (64, 64)) -> Image.Image:
    return Image.new("RGB", size, color)


def _spread(image: Image.Image) -> float:
    return float(np.asarray(image, dtype="float32").std())


class TestExposureProcessor:
    @allure.title("Exposure compensation brightens the pixels and records its settings")
    def test_exposure_compensation(self):
        processor = _configured(ExposureProcessor, "exposure", enabled=True, exposure=1.0)

        result = processor.execute(_solid((64, 64, 64)), ProcessingContext())

        assert float(np.asarray(result.image).mean()) > 64
        assert result.step is not None
        assert result.step["details"]["Exposure"] == "+1.00 EV"
        assert result.step["meta"]["exposure"] == 1.0

    @allure.title("Gamma above one lifts the midtones")
    def test_gamma(self):
        processor = _configured(ExposureProcessor, "exposure", enabled=True, gamma=2.0)

        result = processor.execute(_solid((64, 64, 64)), ProcessingContext())

        assert float(np.asarray(result.image).mean()) > 64
        assert result.step["details"]["Gamma"] == "2.00"

    @allure.title("Exposure settings read their defaults from the config node")
    def test_settings(self):
        node = Node("root")

        assert ExposureSettings.from_node(node.get_node("processing.exposure")) == ExposureSettings()

        node.get_node("processing.exposure.enabled").set_value(True)
        node.get_node("processing.exposure.exposure").set_value(0.75)

        settings = ExposureSettings.from_node(node.get_node("processing.exposure"))
        assert settings.enabled is True
        assert settings.exposure == 0.75


class TestContrastProcessor:
    @allure.title("The S-curve pushes tones away from the midpoint")
    def test_s_curve(self):
        image = _solid((40, 40, 40))
        image.paste((200, 200, 200), (32, 0, 64, 64))
        processor = _configured(ContrastProcessor, "contrast", enabled=True, method="s_curve", strength=1.0)

        result = processor.execute(image, ProcessingContext())
        pixels = np.asarray(result.image)

        assert pixels[:, :32].mean() < 40
        assert pixels[:, 32:].mean() > 200
        assert result.step["details"]["Method"] == "S-curve"

    @allure.title("Adaptive contrast stretches the measured tone endpoints")
    def test_adaptive(self):
        image = _solid((60, 60, 60))
        image.paste((200, 200, 200), (0, 0, 12, 64))
        processor = _configured(
            ContrastProcessor,
            "contrast",
            enabled=True,
            method="adaptive",
            strength=1.0,
            low_percentile=20,
            high_percentile=85,
        )
        context = ProcessingContext()
        processor.prepare(image, context)

        result = processor.execute(image, context)

        assert result.step["details"]["Method"] == "Adaptive tone curve"
        assert context.data["Contrast"].black == 60
        assert context.data["Contrast"].white == 200

    @allure.title("Contrast settings validate the method")
    def test_settings(self):
        node = Node("root")
        settings_node = node.get_node("processing.contrast")
        settings_node.get_node("method").set_value("unknown")

        assert ContrastSettings.from_node(settings_node).method == ContrastSettings.method
        assert ContrastSettings().method == "s_curve"


class TestWhiteBalanceProcessor:
    @allure.title("Gray World detection neutralizes a colour cast")
    def test_gray_world(self):
        processor = _configured(WhiteBalanceProcessor, "white_balance", enabled=True, strength=1.0)

        result = processor.execute(_solid((200, 100, 100)), ProcessingContext())
        red, green, blue = np.asarray(result.image).mean(axis=(0, 1))

        assert max(red, green, blue) - min(red, green, blue) < 8
        assert result.step["summary"] == "Neutralized"

    @allure.title("Manual temperature warms the image")
    def test_temperature(self):
        processor = _configured(
            WhiteBalanceProcessor, "white_balance", enabled=True, method="manual", temperature=1.0, strength=1.0
        )

        result = processor.execute(_solid((100, 100, 100)), ProcessingContext())
        red, _, blue = np.asarray(result.image).mean(axis=(0, 1))

        assert red > blue
        assert result.step["details"]["Method"] == "Manual"

    @allure.title("White balance settings read their defaults")
    def test_settings(self):
        node = Node("root")

        assert WhiteBalanceSettings.from_node(node.get_node("processing.white_balance")) == WhiteBalanceSettings()


class TestLocalContrastProcessor:
    @allure.title("CLAHE increases local detail and records its parameters")
    def test_clahe(self):
        ramp = np.linspace(100, 140, 64 * 64, dtype=np.uint8).reshape(64, 64)
        image = Image.fromarray(np.repeat(ramp[:, :, None], 3, axis=2))
        processor = _configured(LocalContrastProcessor, "local_contrast", enabled=True, clip_limit=3.0, tile_grid=4)

        result = processor.execute(image, ProcessingContext())

        assert _spread(result.image) > _spread(image)
        assert result.step["details"]["Method"] == "CLAHE"
        assert result.step["meta"]["tile_grid"] == 4

    @allure.title("Local contrast settings read their defaults")
    def test_settings(self):
        node = Node("root")

        assert LocalContrastSettings.from_node(node.get_node("processing.local_contrast")) == LocalContrastSettings()


class TestVibranceProcessor:
    @allure.title("Adaptive saturation boosts muted colours more than vivid ones")
    def test_muted_colours_are_boosted(self):
        processor = _configured(VibranceProcessor, "vibrance", enabled=True, strength=1.0)

        muted = np.asarray(processor.execute(_solid((120, 100, 100)), ProcessingContext()).image, dtype="int16")
        vivid = np.asarray(processor.execute(_solid((220, 60, 60)), ProcessingContext()).image, dtype="int16")

        muted_gain = (muted[0, 0, 0] - muted[0, 0, 2]) / 20
        vivid_gain = (vivid[0, 0, 0] - vivid[0, 0, 2]) / 160

        assert muted_gain > 1.0
        assert muted_gain > vivid_gain

    @allure.title("Vibrance settings read their defaults")
    def test_settings(self):
        node = Node("root")

        assert VibranceSettings.from_node(node.get_node("processing.vibrance")) == VibranceSettings()


class TestNoiseReductionProcessor:
    @allure.title("The bilateral filter smooths isolated noisy pixels")
    def test_bilateral(self):
        pixels = np.full((48, 48, 3), 120, dtype=np.uint8)
        pixels[::8, ::8] = 135
        image = Image.fromarray(pixels)
        processor = _configured(NoiseReductionProcessor, "noise_reduction", enabled=True, method="bilateral")

        result = processor.execute(image, ProcessingContext())

        assert _spread(result.image) < _spread(image)
        assert result.step["details"]["Method"] == "Bilateral"
        assert result.step["meta"]["radius"] % 2 == 1

    @allure.title("Non-local means can be selected explicitly")
    def test_non_local_means(self):
        pixels = np.full((32, 32, 3), 120, dtype=np.uint8)
        pixels[::4, ::4] = 240
        processor = _configured(
            NoiseReductionProcessor, "noise_reduction", enabled=True, method="nl_means", strength=5.0
        )

        result = processor.execute(Image.fromarray(pixels), ProcessingContext())

        assert _spread(result.image) < _spread(Image.fromarray(pixels))
        assert result.step["details"]["Method"] == "Non-local means"

    @allure.title("Noise reduction settings validate the method")
    def test_settings(self):
        node = Node("root")
        settings_node = node.get_node("processing.noise_reduction")
        settings_node.get_node("method").set_value("unknown")

        assert NoiseReductionSettings.from_node(settings_node).method == NoiseReductionSettings.method
        assert NoiseReductionSettings().method == "bilateral"


class TestSharpeningProcessor:
    @allure.title("An unsharp mask adds overshoot at edges")
    def test_unsharp_mask(self):
        pixels = np.full((64, 64, 3), 100, dtype=np.uint8)
        pixels[:, 32:] = 140
        processor = _configured(SharpeningProcessor, "sharpening", enabled=True, amount=1.0, radius=1.0, threshold=0.0)

        result = processor.execute(Image.fromarray(pixels), ProcessingContext())
        values = np.asarray(result.image, dtype="int16")

        assert values.min() < 100
        assert values.max() > 140
        assert result.step["details"]["Method"] == "Unsharp mask"

    @allure.title("Sharpening settings read their defaults")
    def test_settings(self):
        node = Node("root")

        assert SharpeningSettings.from_node(node.get_node("processing.sharpening")) == SharpeningSettings()
