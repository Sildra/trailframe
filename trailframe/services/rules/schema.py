"""The photo schema that drives rule validation, evaluation and the editor.

One descriptor describes every field a rule can read: its group, label, kind,
operators, documentation and where its value suggestions come from. The
backend validates and evaluates against it; the frontend renders it and uses it
for expression hints, so both sides always agree on what a rule can say.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from trailframe.models.photo import Photo
from trailframe.services.rules.ast import Condition, Definition
from trailframe.services.rules.metadata import MISSING, exif_value, image_size, simple_value

SCHEMA_VERSION = 1
MAX_CONDITIONS = 20
MAX_GROUP_DEPTH = 4
"""How many nested `all`/`any` levels a definition may hold."""


class RuleValidationError(ValueError):
    """Raised when a rule definition is not well formed."""


# Operator catalog: name -> token, label, documentation.
OPERATORS: dict[str, dict[str, str]] = {
    "eq": {"token": "=", "label": "is", "doc": "The value is equal to the operand."},
    "neq": {"token": "!=", "label": "is not", "doc": "The value differs from the operand."},
    "gt": {"token": ">", "label": "is more than", "doc": "The value is greater than the operand."},
    "gte": {"token": ">=", "label": "is at least", "doc": "The value is greater than or equal to the operand."},
    "lt": {"token": "<", "label": "is less than", "doc": "The value is less than the operand."},
    "lte": {"token": "<=", "label": "is at most", "doc": "The value is less than or equal to the operand."},
    "contains": {"token": "contains", "label": "contains", "doc": "The text or list contains the operand."},
    "not_contains": {
        "token": "!contains",
        "label": "does not contain",
        "doc": "The text or list does not contain the operand.",
    },
    "in": {"token": "in", "label": "is one of", "doc": "The value is one of the listed operands."},
}

KIND_OPERATORS: dict[str, tuple[str, ...]] = {
    "text": ("eq", "neq", "contains", "in"),
    "number": ("eq", "neq", "gt", "gte", "lt", "lte"),
    "date": ("eq", "neq", "gt", "gte", "lt", "lte"),
    "bool": ("eq", "neq"),
    "enum": ("eq", "neq", "in"),
    "list": ("contains", "not_contains"),
    "detection": ("present", "absent"),
}

NUMERIC_OPS = frozenset({"eq", "neq", "gt", "gte", "lt", "lte"})


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One metadata field a rule can read."""

    path: str
    group: str
    label: str
    kind: str
    description: str
    values: str = "none"
    """Where suggestions come from: `none`, `static`, `distinct`, `objects`, `tags`, `scanners`."""
    static_values: tuple[str, ...] = ()
    computed: bool = False
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit: str = ""

    @property
    def operators(self) -> tuple[str, ...]:
        return KIND_OPERATORS[self.kind]


@dataclass(frozen=True, slots=True)
class MetricSpec:
    """One numeric metric of a detection, expressed in the unit `unit`."""

    name: str
    label: str
    description: str
    min: float = 0.0
    max: float = 100.0
    step: float = 1.0
    unit: str = ""


def metric_scale(spec: MetricSpec) -> float:
    """How many stored units make one rule unit (`confidence` is stored as 0..1)."""
    return 100.0 if spec.unit == "%" else 1.0


@dataclass(frozen=True, slots=True)
class GroupSpec:
    """A labelled group of fields, rendered as a section in the editor."""

    name: str
    label: str
    fields: tuple[FieldSpec, ...] = field(default_factory=tuple)


OBJECT_LABELS: tuple[str, ...] = (
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "airplane",
    "bus",
    "train",
    "truck",
    "boat",
    "bird",
    "cat",
    "dog",
    "horse",
    "sheep",
    "cow",
    "elephant",
    "bear",
    "zebra",
    "giraffe",
    "backpack",
    "umbrella",
    "handbag",
    "tie",
    "suitcase",
    "frisbee",
    "skis",
    "snowboard",
    "sports ball",
    "kite",
    "skateboard",
    "surfboard",
    "tennis racket",
    "bottle",
    "wine glass",
    "cup",
    "fork",
    "knife",
    "spoon",
    "bowl",
    "banana",
    "apple",
    "sandwich",
    "orange",
    "broccoli",
    "carrot",
    "hot dog",
    "pizza",
    "donut",
    "cake",
    "chair",
    "couch",
    "potted plant",
    "bed",
    "dining table",
    "toilet",
    "tv",
    "laptop",
    "mouse",
    "remote",
    "keyboard",
    "cell phone",
    "microwave",
    "oven",
    "toaster",
    "sink",
    "refrigerator",
    "book",
    "clock",
    "vase",
    "scissors",
    "teddy bear",
    "hair drier",
    "toothbrush",
)

DETECTION = FieldSpec(
    path="objects",
    group="Objects",
    label="Detected object",
    kind="detection",
    description="An object found by the Object scanner, with its confidence and the share of the image it covers.",
    values="objects",
)

DETECTION_METRICS: tuple[MetricSpec, ...] = (
    MetricSpec("confidence", "Confidence", "How sure the detector is, from 0 to 100 percent.", unit="%"),
    MetricSpec("surface", "Surface", "Share of the image area the object covers, from 0 to 100 percent.", unit="%"),
)
METRIC_BY_NAME: dict[str, MetricSpec] = {metric.name: metric for metric in DETECTION_METRICS}

GROUPS: tuple[GroupSpec, ...] = (
    GroupSpec("Objects", "Objects", (DETECTION,)),
    GroupSpec(
        "Camera",
        "Camera",
        (
            FieldSpec(
                "exif.Make", "Camera", "Camera make", "text", "EXIF Make, the camera manufacturer.", values="distinct"
            ),
            FieldSpec(
                "exif.Model",
                "Camera",
                "Camera model",
                "text",
                "EXIF Model, the camera or phone model.",
                values="distinct",
            ),
            FieldSpec("exif.LensModel", "Camera", "Lens", "text", "EXIF LensModel.", values="distinct"),
            FieldSpec(
                "exif.FNumber",
                "Camera",
                "Aperture",
                "number",
                "EXIF FNumber, stored as a ratio such as '28/10'.",
                min=0.0,
                max=64.0,
                step=0.1,
                unit="f/",
            ),
            FieldSpec("exif.ISOSpeedRatings", "Camera", "ISO", "number", "EXIF ISOSpeedRatings.", min=0.0, step=1.0),
            FieldSpec(
                "exif.FocalLength",
                "Camera",
                "Focal length",
                "number",
                "EXIF FocalLength, stored as a ratio such as '35/1'.",
                min=0.0,
                step=1.0,
                unit="mm",
            ),
            FieldSpec(
                "exif.ExposureTime",
                "Camera",
                "Exposure time",
                "number",
                "EXIF ExposureTime in seconds, stored as a ratio such as '1/250'.",
                min=0.0,
                step=0.0001,
                unit="s",
            ),
        ),
    ),
    GroupSpec(
        "Image",
        "Image",
        (
            FieldSpec(
                "width",
                "Image",
                "Width",
                "number",
                "Image width in pixels, from the EXIF dimensions.",
                computed=True,
                min=0.0,
                step=1.0,
                unit="px",
            ),
            FieldSpec(
                "height",
                "Image",
                "Height",
                "number",
                "Image height in pixels, from the EXIF dimensions.",
                computed=True,
                min=0.0,
                step=1.0,
                unit="px",
            ),
            FieldSpec(
                "orientation",
                "Image",
                "Orientation",
                "enum",
                "`landscape`, `portrait` or `square`.",
                values="static",
                static_values=("landscape", "portrait", "square"),
            ),
        ),
    ),
    GroupSpec(
        "Place",
        "Place",
        (
            FieldSpec(
                "country", "Place", "Country", "text", "The country resolved from the GPS position.", values="distinct"
            ),
            FieldSpec(
                "location",
                "Place",
                "Location",
                "text",
                "The place name resolved from the GPS position.",
                values="distinct",
            ),
            FieldSpec("date", "Place", "Date taken", "date", "The capture date, as `YYYY-MM-DD`."),
            FieldSpec(
                "latitude",
                "Place",
                "Latitude",
                "number",
                "The GPS latitude in degrees.",
                min=-90.0,
                max=90.0,
                step=0.000001,
            ),
            FieldSpec(
                "longitude",
                "Place",
                "Longitude",
                "number",
                "The GPS longitude in degrees.",
                min=-180.0,
                max=180.0,
                step=0.000001,
            ),
        ),
    ),
    GroupSpec(
        "File",
        "File",
        (
            FieldSpec("filename", "File", "Filename", "text", "The file name, including its extension."),
            FieldSpec(
                "file_size", "File", "File size", "number", "The file size in bytes.", min=0.0, step=1.0, unit="B"
            ),
            FieldSpec("is_favorite", "File", "Favorite", "bool", "Whether the photo is marked as a favorite."),
            FieldSpec("tags", "File", "Current tags", "list", "The tags the photo already carries.", values="tags"),
            FieldSpec(
                "scanners",
                "File",
                "Scanners run",
                "list",
                "The scanners that already processed the photo.",
                values="scanners",
            ),
        ),
    ),
    GroupSpec(
        "Quality",
        "Quality",
        (
            FieldSpec(
                "scores.brisque",
                "Quality",
                "Quality score",
                "number",
                "The BRISQUE score, when the quality scanner ran.",
            ),
        ),
    ),
)

FIELDS: tuple[FieldSpec, ...] = tuple(field_spec for group in GROUPS for field_spec in group.fields)
FIELD_BY_PATH: dict[str, FieldSpec] = {field_spec.path: field_spec for field_spec in FIELDS}


# ----------------------------------------------------------------------
# Schema payload
# ----------------------------------------------------------------------


def _field_json(spec: FieldSpec) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": spec.path,
        "group": spec.group,
        "label": spec.label,
        "description": spec.description,
        "kind": spec.kind,
        "operators": list(spec.operators),
        "computed": spec.computed,
        "values": {"source": spec.values, "values": list(spec.static_values)},
    }

    for name in ("min", "max", "step", "unit"):
        value = getattr(spec, name)

        if value not in (None, ""):
            payload[name] = value

    if spec.kind == "detection":
        payload["detection"] = {
            "label_field": "label",
            "label_values": {"source": spec.values, "values": list(OBJECT_LABELS)},
            "operators": list(spec.operators),
            "metrics": [
                {
                    "name": metric.name,
                    "label": metric.label,
                    "description": metric.description,
                    "kind": "number",
                    "operators": list(KIND_OPERATORS["number"]),
                    "min": metric.min,
                    "max": metric.max,
                    "step": metric.step,
                    "unit": metric.unit,
                }
                for metric in DETECTION_METRICS
            ],
        }

    return payload


def schema() -> dict[str, Any]:
    """The photo schema, as served to the rule editor."""
    return {
        "version": SCHEMA_VERSION,
        "capabilities": ["tokens", "completions", "docs", "snippets"],
        "grammar": {
            "keywords": [
                {"token": "and", "kind": "logical", "doc": "Both sides must match."},
                {"token": "or", "kind": "logical", "doc": "Either side may match."},
                {"token": "has", "kind": "detection", "doc": "The photo contains a detected object."},
                {"token": "no", "kind": "detection", "doc": 'Negates a detection: `has no "dog"`.'},
                {"token": "with", "kind": "detection", "doc": "Narrows a detection by its metrics."},
                {"token": "is", "kind": "comparison", "doc": "Compares a field: `is_favorite is true`."},
                {"token": "not", "kind": "comparison", "doc": "Negates a comparison: `is not true`."},
                {"token": "true", "kind": "boolean", "doc": "A true boolean value."},
                {"token": "false", "kind": "boolean", "doc": "A false boolean value."},
            ],
            "operators": {name: dict(info, name=name) for name, info in OPERATORS.items()},
        },
        "detection": {
            "path": DETECTION.path,
            "label_field": "label",
            "label_values": {"source": DETECTION.values, "values": list(OBJECT_LABELS)},
            "operators": list(KIND_OPERATORS["detection"]),
            "metrics": _field_json(DETECTION)["detection"]["metrics"],
        },
        "groups": [
            {
                "name": group.name,
                "label": group.label,
                "fields": [_field_json(field_spec) for field_spec in group.fields],
            }
            for group in GROUPS
        ],
    }


def field_for(path: str) -> FieldSpec | None:
    if path.startswith(("exif.", "scores.")):
        return FIELD_BY_PATH.get(path)

    return FIELD_BY_PATH.get(path)


# ----------------------------------------------------------------------
# Typed value resolution
# ----------------------------------------------------------------------


def as_number(value: Any) -> float | None:
    """Read a number from an EXIF ratio, a numeric string or a number."""
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()

    if "/" in text:
        numerator, _, denominator = text.partition("/")

        try:
            return float(numerator) / float(denominator)
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    match = re.match(r"\s*(-?\d+(?:\.\d+)?)", text)

    return float(match.group(1)) if match else None


def resolve(photo: Photo, path: str) -> Any:
    """The typed value of `path` for `photo` (MISSING when the field is unknown)."""
    spec = field_for(path)

    if spec is None:
        return MISSING

    if path == "objects":
        return photo.objects or []

    if path.startswith("exif."):
        raw = exif_value(photo, path)

        return as_number(raw) if spec.kind == "number" else raw

    if path.startswith("scores."):
        raw = (photo.scores or {}).get(path.split(".", 1)[1])

        return as_number(raw) if spec.kind == "number" else raw

    if path == "width":
        return image_size(photo)[0]

    if path == "height":
        return image_size(photo)[1]

    if path == "orientation":
        width, height = image_size(photo)

        if not width or not height:
            return None

        if width == height:
            return "square"

        return "landscape" if width > height else "portrait"

    if path == "date":
        return photo.date.date().isoformat() if photo.date else None

    value = simple_value(photo, path)

    if value is MISSING:
        return MISSING

    return value


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------


def _require_value(condition: Condition) -> None:
    if condition.type != "scalar":
        return

    spec = field_for(condition.path)

    if spec is None:
        raise RuleValidationError(f"Unknown metadata field: {condition.path}")

    op = condition.op

    if op not in spec.operators:
        raise RuleValidationError(f"'{op}' cannot be used on '{condition.path}'")

    value = condition.value

    if op == "in":
        if not isinstance(value, list) or not value:
            raise RuleValidationError("'in' needs a list of values")

        values: list[Any] = value
    else:
        if value is None or value == "":
            raise RuleValidationError(f"'{condition.path}' needs a value")

        values = [value]

    if spec.kind in ("number",):
        for item in values:
            if as_number(item) is None:
                raise RuleValidationError(f"'{condition.path}' needs a number")

    if spec.kind == "date":
        for item in values:
            try:
                date.fromisoformat(str(item))
            except ValueError as exception:
                raise RuleValidationError(f"'{condition.path}' needs a YYYY-MM-DD date") from exception

    if spec.kind == "bool" and not isinstance(value, bool):
        raise RuleValidationError(f"'{condition.path}' needs true or false")


def _count(conditions: list[Condition]) -> int:
    total = 0

    for condition in conditions:
        if condition.type == "group":
            total += _count(condition.conditions)
        else:
            total += 1

    return total


def _validate_conditions(conditions: list[Condition], depth: int) -> None:
    if depth > MAX_GROUP_DEPTH:
        raise RuleValidationError(f"Groups can nest at most {MAX_GROUP_DEPTH} levels")

    if not conditions:
        raise RuleValidationError("Every rule and group needs at least one condition")

    for condition in conditions:
        if condition.type == "group":
            _validate_conditions(condition.conditions, depth + 1)

        elif condition.type == "detection":
            known = {metric.name for metric in DETECTION_METRICS}

            for metric in condition.metrics:
                if metric.name not in known:
                    raise RuleValidationError(f"Unknown object metric: {metric.name}")

                if metric.op not in KIND_OPERATORS["number"]:
                    raise RuleValidationError(f"'{metric.op}' cannot be used on '{metric.name}'")

                if not math.isfinite(metric.value):
                    raise RuleValidationError(f"'{metric.name}' needs a finite number")

                spec = METRIC_BY_NAME[metric.name]
                low, high = spec.min, spec.max

                if not low <= metric.value <= high:
                    raise RuleValidationError(f"'{metric.name}' must be between {low:g} and {high:g}")

        else:
            _require_value(condition)


def validate_definition(definition: Definition) -> Definition:
    """Reject a definition whose paths, operators or values the schema does not allow."""
    if not definition.conditions:
        raise RuleValidationError("The rule needs at least one condition")

    if _count(definition.conditions) > MAX_CONDITIONS:
        raise RuleValidationError(f"A rule holds at most {MAX_CONDITIONS} conditions")

    _validate_conditions(definition.conditions, 0)

    return definition


__all__ = [
    "DETECTION",
    "DETECTION_METRICS",
    "FIELDS",
    "FIELD_BY_PATH",
    "GROUPS",
    "KIND_OPERATORS",
    "MAX_CONDITIONS",
    "MAX_GROUP_DEPTH",
    "METRIC_BY_NAME",
    "NUMERIC_OPS",
    "OBJECT_LABELS",
    "OPERATORS",
    "SCHEMA_VERSION",
    "FieldSpec",
    "MetricSpec",
    "RuleValidationError",
    "as_number",
    "field_for",
    "metric_scale",
    "resolve",
    "schema",
    "validate_definition",
]
