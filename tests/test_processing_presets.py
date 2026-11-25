from __future__ import annotations

import allure
import pytest
from fastapi import HTTPException

from trailframe.api.photos import (
    ReprocessExposure,
    ReprocessRequest,
    ReprocessTilt,
    ReprocessVibrance,
    _build_reprocess_overrides,
)
from trailframe.services.processors.presets import (
    DEFAULT_PRESETS,
    MODES,
    PresetError,
    canonical_mode,
    preset_names,
    resolve,
)


class TestPresetResolution:
    @allure.title("Every correction has a default preset with both automatic and manual values")
    def test_catalogue_shape(self):
        assert set(DEFAULT_PRESETS) == {
            "Exposure",
            "White balance",
            "Contrast",
            "Local contrast",
            "Vibrance",
            "Tilt",
            "Noise reduction",
            "Sharpening",
        }

        for processor, name in DEFAULT_PRESETS.items():
            assert name in preset_names(processor)
            enabled, resolved = resolve(processor, "automatic", name, {})
            assert enabled is True
            assert resolved["mode"] == "automatic"
            assert resolved["preset"] == name

    @allure.title("Mode aliases are canonicalized")
    def test_canonical_mode(self):
        assert canonical_mode(None) is None
        assert canonical_mode("AUTO") == "automatic"
        assert canonical_mode(" manual ") == "manual"
        assert canonical_mode("sideways") is None
        assert MODES == {"off", "automatic", "manual"}

    @allure.title("A legacy enabled payload keeps its values as a manual custom recipe")
    def test_legacy_manual_values(self):
        enabled, resolved = resolve("Exposure", None, None, {"enabled": True, "exposure": 1.2, "gamma": 1.4})

        assert enabled is True
        assert resolved == {"mode": "manual", "preset": "custom", "exposure": 1.2, "gamma": 1.4}

    @allure.title("A named manual preset seeds editable settings")
    def test_manual_preset_values(self):
        enabled, resolved = resolve("White balance", "manual", "warm", {})

        assert enabled is True
        assert resolved == {
            "mode": "manual",
            "preset": "warm",
            "method": "manual",
            "strength": 0.6,
            "temperature": 0.25,
            "tint": 0.05,
        }

    @allure.title("Manual mode uses supplied values rather than the preset's defaults")
    def test_manual_supplied_values_win(self):
        _, resolved = resolve("Vibrance", "manual", "vivid", {"strength": 0.9})

        assert resolved["preset"] == "vivid"
        assert resolved["strength"] == 0.9

    @allure.title("Automatic mode ignores client numbers but keeps the separate crop selector")
    def test_automatic_preset_is_authoritative(self):
        enabled, resolved = resolve(
            "White balance", "auto", "cool", {"method": "manual", "strength": 1, "temperature": 1, "tint": 1}
        )

        assert enabled is True
        assert resolved == {
            "method": "gray_world",
            "strength": 0.45,
            "temperature": -0.15,
            "tint": -0.05,
            "mode": "automatic",
            "preset": "cool",
        }

        _, tilt = resolve("Tilt", "automatic", "assertive", {"angle": 3, "min_confidence": 0.99, "crop_mode": "none"})
        assert tilt["min_confidence"] == 0.55
        assert tilt["max_angle"] == 6.0
        assert tilt["crop_mode"] == "none"
        assert "angle" not in tilt

    @allure.title("Off mode drops correction settings and uses the default preset")
    def test_off_mode(self):
        enabled, resolved = resolve("Exposure", "off", "gentle", {"exposure": 2, "gamma": 2})

        assert enabled is False
        assert resolved == {"mode": "off", "preset": "gentle"}

    @allure.title("Off mode keeps the crop selector and rejects custom presets")
    def test_off_validation(self):
        _, tilt = resolve("Tilt", "off", "standard", {"crop_mode": "none"})
        assert tilt == {"mode": "off", "preset": "standard", "crop_mode": "none"}

        with pytest.raises(PresetError, match="manual mode"):
            resolve("Tilt", "off", "custom", {})

    @allure.title("Unknown modes and presets are rejected")
    def test_invalid_names(self):
        with pytest.raises(PresetError, match="Unknown correction mode"):
            resolve("Exposure", "sideways", None, {})

        with pytest.raises(PresetError, match="Unknown preset"):
            resolve("Exposure", "manual", "nope", {})

        with pytest.raises(PresetError, match="named preset"):
            resolve("Exposure", "automatic", "custom", {})


class TestOverrideTranslation:
    @allure.title("Automatic API overrides ignore client numbers")
    def test_automatic_override(self):
        overrides = _build_reprocess_overrides(
            ReprocessRequest(exposure=ReprocessExposure(mode="automatic", preset="strong", exposure=0, gamma=1))
        )

        override = overrides["Exposure"]
        assert override.enabled is True
        assert override.mode == "automatic"
        assert override.preset == "strong"
        assert override.exposure == 0.6
        assert override.gamma == 0.9

    @allure.title("Legacy API overrides stay manual")
    def test_legacy_override(self):
        overrides = _build_reprocess_overrides(ReprocessRequest(exposure=ReprocessExposure(enabled=True, exposure=1.2)))

        override = overrides["Exposure"]
        assert override.mode == "manual"
        assert override.preset == "custom"
        assert override.exposure == 1.2

    @allure.title("Off API overrides are disabled and validated")
    def test_off_override(self):
        overrides = _build_reprocess_overrides(
            ReprocessRequest(vibrance=ReprocessVibrance(mode="off", preset="natural", strength=0.8))
        )

        override = overrides["Vibrance"]
        assert override.enabled is False
        assert override.mode == "off"
        assert override.preset == "natural"
        assert override.strength is None

    @allure.title("A legacy tilt angle remains a manual override")
    def test_legacy_tilt_angle(self):
        overrides = _build_reprocess_overrides(ReprocessRequest(tilt=ReprocessTilt(angle=5)))

        override = overrides["Tilt"]
        assert override.enabled is True
        assert override.mode == "manual"
        assert override.preset == "custom"
        assert override.angle == 5

    @allure.title("A tilt preset tunes detection without rotating by client angle")
    def test_tilt_preset(self):
        overrides = _build_reprocess_overrides(
            ReprocessRequest(tilt=ReprocessTilt(mode="auto", preset="assertive", angle=5, crop_mode="none"))
        )

        override = overrides["Tilt"]
        assert override.mode == "automatic"
        assert override.preset == "assertive"
        assert override.min_confidence == 0.55
        assert override.max_angle == 6.0
        assert override.crop_mode == "none"
        assert override.angle is None

    @allure.title("Invalid mode and preset payloads become HTTP 400")
    def test_invalid_payloads(self):
        requests = [
            ReprocessRequest(exposure=ReprocessExposure(mode="sideways")),
            ReprocessRequest(exposure=ReprocessExposure(mode="manual", preset="nope")),
            ReprocessRequest(exposure=ReprocessExposure(mode="automatic", preset="custom")),
            ReprocessRequest(vibrance=ReprocessVibrance(mode="off", preset="custom")),
            ReprocessRequest(tilt=ReprocessTilt(mode="manual")),
        ]

        for request in requests:
            with pytest.raises(HTTPException) as error:
                _build_reprocess_overrides(request)
            assert error.value.status_code == 400
