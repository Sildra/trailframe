"""Named presets for the per-photo processing corrections.

A preset has two faces: ``automatic`` values are applied when the editor leaves
the decision to the processor (numeric fields are locked in the UI), and
``manual`` values seed the editable controls. The backend is the authority for
both faces so a saved recipe can be replayed without the editor.
"""

from __future__ import annotations

from typing import Any

CUSTOM = "custom"
MODES = frozenset({"off", "automatic", "manual"})
ALIASES = {"auto": "automatic"}

# ``enabled``/``mode``/``preset`` are transport fields, never processor settings.
_TRANSPORT_KEYS = frozenset({"enabled", "mode", "preset"})
# Crop mode belongs to the separate Crop accordion: it stays editable and must
# still be validated in automatic and off modes.
_PRESERVED_AUTO_KEYS = frozenset({"crop_mode"})

_PRESETS: dict[str, dict[str, dict[str, dict[str, Any]]]] = {
    "Exposure": {
        "gentle": {"automatic": {"exposure": 0.15, "gamma": 1.02}, "manual": {"exposure": 0.15, "gamma": 1.02}},
        "balanced": {"automatic": {"exposure": 0.3, "gamma": 0.97}, "manual": {"exposure": 0.0, "gamma": 1.0}},
        "strong": {"automatic": {"exposure": 0.6, "gamma": 0.9}, "manual": {"exposure": 0.6, "gamma": 0.9}},
    },
    "White balance": {
        "neutral": {
            "automatic": {"method": "gray_world", "strength": 0.35, "temperature": 0.0, "tint": 0.0},
            "manual": {"method": "gray_world", "strength": 0.35, "temperature": 0.0, "tint": 0.0},
        },
        "warm": {
            "automatic": {"method": "gray_world", "strength": 0.45, "temperature": 0.15, "tint": 0.05},
            "manual": {"method": "manual", "strength": 0.6, "temperature": 0.25, "tint": 0.05},
        },
        "cool": {
            "automatic": {"method": "gray_world", "strength": 0.45, "temperature": -0.15, "tint": -0.05},
            "manual": {"method": "manual", "strength": 0.6, "temperature": -0.25, "tint": -0.05},
        },
        "shade": {
            "automatic": {"method": "gray_world", "strength": 0.7, "temperature": 0.1, "tint": 0.0},
            "manual": {"method": "gray_world", "strength": 0.8, "temperature": 0.1, "tint": 0.0},
        },
    },
    "Contrast": {
        "soft": {
            "automatic": {"method": "adaptive", "strength": 0.3, "low_percentile": 8, "high_percentile": 92},
            "manual": {"method": "s_curve", "strength": 0.3, "low_percentile": 8, "high_percentile": 92},
        },
        "standard": {
            "automatic": {"method": "adaptive", "strength": 0.55, "low_percentile": 5, "high_percentile": 95},
            "manual": {"method": "adaptive", "strength": 0.55, "low_percentile": 5, "high_percentile": 95},
        },
        "punchy": {
            "automatic": {"method": "adaptive", "strength": 0.8, "low_percentile": 3, "high_percentile": 97},
            "manual": {"method": "adaptive", "strength": 0.8, "low_percentile": 3, "high_percentile": 97},
        },
    },
    "Local contrast": {
        "subtle": {
            "automatic": {"clip_limit": 1.0, "tile_grid": 8, "strength": 0.3},
            "manual": {"clip_limit": 1.0, "tile_grid": 8, "strength": 0.3},
        },
        "standard": {
            "automatic": {"clip_limit": 2.0, "tile_grid": 8, "strength": 0.6},
            "manual": {"clip_limit": 2.0, "tile_grid": 8, "strength": 0.6},
        },
        "strong": {
            "automatic": {"clip_limit": 3.5, "tile_grid": 8, "strength": 0.9},
            "manual": {"clip_limit": 3.5, "tile_grid": 8, "strength": 0.9},
        },
    },
    "Vibrance": {
        "natural": {"automatic": {"strength": 0.25}, "manual": {"strength": 0.25}},
        "vivid": {"automatic": {"strength": 0.5}, "manual": {"strength": 0.5}},
        "strong": {"automatic": {"strength": 0.8}, "manual": {"strength": 0.8}},
    },
    "Tilt": {
        "conservative": {
            "automatic": {"min_confidence": 0.85, "max_angle": 2.5, "crop_mode": "maximum_valid_rectangle"},
            "manual": {"crop_mode": "maximum_valid_rectangle"},
        },
        "standard": {
            "automatic": {"crop_mode": "maximum_valid_rectangle"},
            "manual": {"crop_mode": "maximum_valid_rectangle"},
        },
        "assertive": {
            "automatic": {"min_confidence": 0.55, "max_angle": 6.0, "crop_mode": "maximum_valid_rectangle"},
            "manual": {"crop_mode": "maximum_valid_rectangle"},
        },
    },
    "Noise reduction": {
        "light": {
            "automatic": {"method": "bilateral", "radius": 3, "sigma_color": 20, "sigma_space": 20, "strength": 4},
            "manual": {"method": "bilateral", "radius": 3, "sigma_color": 20, "sigma_space": 20, "strength": 4},
        },
        "standard": {
            "automatic": {"method": "bilateral", "radius": 5, "sigma_color": 35, "sigma_space": 35, "strength": 10},
            "manual": {"method": "bilateral", "radius": 5, "sigma_color": 35, "sigma_space": 35, "strength": 10},
        },
        "strong": {
            "automatic": {"method": "nl_means", "radius": 5, "sigma_color": 35, "sigma_space": 35, "strength": 14},
            "manual": {"method": "nl_means", "radius": 5, "sigma_color": 35, "sigma_space": 35, "strength": 14},
        },
    },
    "Sharpening": {
        "soft": {
            "automatic": {"radius": 1.0, "amount": 0.3, "threshold": 4},
            "manual": {"radius": 1.0, "amount": 0.3, "threshold": 4},
        },
        "standard": {
            "automatic": {"radius": 1.0, "amount": 0.5, "threshold": 2},
            "manual": {"radius": 1.0, "amount": 0.5, "threshold": 2},
        },
        "detail": {
            "automatic": {"radius": 1.2, "amount": 0.9, "threshold": 1},
            "manual": {"radius": 1.2, "amount": 0.9, "threshold": 1},
        },
    },
}

DEFAULT_PRESETS = {
    "Exposure": "balanced",
    "White balance": "neutral",
    "Contrast": "standard",
    "Local contrast": "standard",
    "Vibrance": "natural",
    "Tilt": "standard",
    "Noise reduction": "standard",
    "Sharpening": "standard",
}


class PresetError(ValueError):
    """An unknown mode or preset name."""


def canonical_mode(value: str | None) -> str | None:
    if value is None:
        return None

    mode = ALIASES.get(value.strip().lower(), value.strip().lower())

    return mode if mode in MODES else None


def preset_names(processor: str) -> list[str]:
    return list(_PRESETS.get(processor, {}))


def resolve(
    processor: str, mode: str | None, preset: str | None, values: dict[str, Any]
) -> tuple[bool, dict[str, Any]]:
    """Return ``(enabled, override_fields)`` for one correction payload.

    ``values`` is the raw payload excluding ``None`` fields. An omitted ``mode``
    keeps the old ``enabled`` semantics so older clients still work.
    """

    raw_values = {key: value for key, value in values.items() if key not in _TRANSPORT_KEYS}
    normalized = canonical_mode(mode)
    enabled_field = values.get("enabled")

    if normalized is None:
        if mode is not None:
            raise PresetError(f"Unknown correction mode '{mode}'")
        normalized = "manual" if enabled_field else "off"

    if normalized == "off":
        name = (preset or "").strip().lower()

        if name == CUSTOM:
            raise PresetError("Custom preset is only available in manual mode")

        if name and name not in preset_names(processor):
            raise PresetError(f"Unknown preset '{preset}' for {processor}")

        resolved = {"mode": "off", "preset": name or DEFAULT_PRESETS.get(processor, CUSTOM)}
        resolved.update({key: value for key, value in raw_values.items() if key in _PRESERVED_AUTO_KEYS})
        return False, resolved

    explicit_preset = preset is not None
    name = (preset or "").strip().lower()
    known = preset_names(processor)

    if not name:
        name = CUSTOM if raw_values else DEFAULT_PRESETS.get(processor, CUSTOM)

    if name != CUSTOM and name not in known:
        raise PresetError(f"Unknown preset '{preset}' for {processor}")

    if normalized == "automatic" and name == CUSTOM and explicit_preset:
        raise PresetError("Automatic mode requires a named preset")

    catalogue = _PRESETS.get(processor, {}).get(name, {})
    resolved = dict(catalogue.get(normalized, {}))

    # A custom automatic payload is legacy: keep the explicit fields instead of
    # inventing preset values. A named automatic preset is authoritative, so the
    # numeric fields sent by an editor are ignored while automatic mode is on.
    if name == CUSTOM or normalized == "manual":
        resolved.update(raw_values)
    else:
        resolved.update({key: value for key, value in raw_values.items() if key in _PRESERVED_AUTO_KEYS})

    resolved["mode"] = normalized
    resolved["preset"] = name

    return True, resolved
