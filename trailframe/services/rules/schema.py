"""The photo schema that drives rule validation, evaluation and the editor.

One descriptor describes every value a rule can read: scalar fields (path,
type, unit, range, suggestions) and collections (path plus its filterable
elements). The backend validates against it and the frontend renders it, while
evaluation walks the declared `source` generically over `photo_view`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from trailframe.models.photo import Photo
from trailframe.services.rules.ast import Condition, Definition, ElementCondition, ScalarCondition
from trailframe.services.rules.metadata import MISSING, photo_view, walk

SCHEMA_VERSION = 2
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
}

NUMERIC_OPS = frozenset({"eq", "neq", "gt", "gte", "lt", "lte"})

QUANTIFIERS: tuple[str, ...] = ("any", "none", "one", "all")
"""How many elements of a collection must satisfy the filter.

`any` and `none` are existential (false/true on an empty collection); `one`
requires exactly one match; `all` is true when every element matches (and is
vacuously true when the collection is empty).
"""


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One scalar value a rule can read."""

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
    source: str = ""
    """The path walked over `photo_view`; defaults to `path`."""

    @property
    def operators(self) -> tuple[str, ...]:
        return KIND_OPERATORS[self.kind]


@dataclass(frozen=True, slots=True)
class ElementSpec:
    """One key of a collection element a rule can filter on."""

    key: str
    label: str
    kind: str
    description: str
    values: str = "none"
    static_values: tuple[str, ...] = ()
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit: str = ""

    @property
    def operators(self) -> tuple[str, ...]:
        return KIND_OPERATORS[self.kind]


@dataclass(frozen=True, slots=True)
class CollectionSpec:
    """A multi-valued field, filtered element by element."""

    path: str
    group: str
    label: str
    description: str
    elements: tuple[ElementSpec, ...] = field(default_factory=tuple)


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

OBJECTS = CollectionSpec(
    path="objects",
    group="Objects",
    label="Detected objects",
    description="The objects the Object scanner found, each with its confidence and surface.",
    elements=(
        ElementSpec("label", "Label", "text", "The detected object label.", values="objects"),
        ElementSpec(
            "confidence",
            "Confidence",
            "number",
            "How sure the detector is, from 0 to 100 percent.",
            min=0.0,
            max=1.0,
            step=0.01,
            unit="%",
        ),
        ElementSpec(
            "surface",
            "Surface",
            "number",
            "Share of the image area the object covers, from 0 to 100 percent.",
            min=0.0,
            max=1.0,
            step=0.01,
            unit="%",
        ),
    ),
)

PROCESSING = CollectionSpec(
    path="processing",
    group="Processing",
    label="Processing steps",
    description="The preprocessing recipe recorded for the photo.",
    elements=(
        ElementSpec(
            "step", "Step", "enum", "The step name.", values="static", static_values=("tilt", "crop", "rescale")
        ),
        ElementSpec("meta.applied", "Tilt applied", "bool", "Whether the tilt correction was applied."),
        ElementSpec(
            "meta.crop_mode",
            "Crop mode",
            "enum",
            "How the tilt step cropped the photo.",
            values="static",
            static_values=("maximum_valid_rectangle", "none"),
        ),
    ),
)

ALTERNATIVES = CollectionSpec(
    path="alternatives",
    group="Processing",
    label="Processed files",
    description="The alternatives generated by the Processing scanner.",
    elements=(
        ElementSpec(
            "target_size",
            "Target size",
            "number",
            "The longest edge this alternative was generated for.",
            min=0.0,
            step=1.0,
            unit="px",
        ),
        ElementSpec("width", "Width", "number", "The alternative's width in pixels.", min=0.0, step=1.0, unit="px"),
        ElementSpec("height", "Height", "number", "The alternative's height in pixels.", min=0.0, step=1.0, unit="px"),
        ElementSpec(
            "file_size", "File size", "number", "The alternative's size in bytes.", min=0.0, step=1.0, unit="B"
        ),
        ElementSpec("format", "Format", "text", "The encoded format."),
        ElementSpec("main", "Main file", "bool", "Whether this alternative is the main one."),
    ),
)

COLLECTIONS: tuple[CollectionSpec, ...] = (OBJECTS, PROCESSING, ALTERNATIVES)
COLLECTION_BY_PATH: dict[str, CollectionSpec] = {spec.path: spec for spec in COLLECTIONS}

GROUPS: tuple[GroupSpec, ...] = (
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
                "Image width in pixels, from the main file or the EXIF dimensions.",
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
                "Image height in pixels, from the main file or the EXIF dimensions.",
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
        "Processing",
        "Processing",
        (
            FieldSpec(
                "processing.tilt.applied",
                "Processing",
                "Tilt applied",
                "bool",
                "Whether the tilt correction was applied to the alternatives.",
                source="processing[step=tilt].meta.applied",
            ),
            FieldSpec(
                "processing.tilt.crop_mode",
                "Processing",
                "Tilt crop mode",
                "enum",
                "How the tilt step cropped the photo.",
                values="static",
                static_values=("maximum_valid_rectangle", "none"),
                source="processing[step=tilt].meta.crop_mode",
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

    return payload


def _element_json(spec: ElementSpec) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "key": spec.key,
        "label": spec.label,
        "description": spec.description,
        "kind": spec.kind,
        "operators": list(spec.operators),
        "values": {"source": spec.values, "values": list(spec.static_values)},
    }

    for name in ("min", "max", "step", "unit"):
        value = getattr(spec, name)

        if value not in (None, ""):
            payload[name] = value

    return payload


def _collection_json(spec: CollectionSpec) -> dict[str, Any]:
    return {
        "path": spec.path,
        "group": spec.group,
        "label": spec.label,
        "description": spec.description,
        "quantifiers": list(QUANTIFIERS),
        "elements": [_element_json(element) for element in spec.elements],
    }


def schema() -> dict[str, Any]:
    """The photo schema, as served to the rule editor."""
    return {
        "version": SCHEMA_VERSION,
        "capabilities": ["tokens", "completions", "docs", "snippets"],
        "grammar": {
            "keywords": [
                {"token": "and", "kind": "logical", "doc": "Both sides must match."},
                {"token": "or", "kind": "logical", "doc": "Either side may match."},
                {"token": "not", "kind": "logical", "doc": "Negates the condition that follows."},
                {"token": "has", "kind": "quantifier", "doc": "Says how many elements must match the filter."},
                {"token": "any", "kind": "quantifier", "doc": "At least one element matches."},
                {"token": "none", "kind": "quantifier", "doc": "No element matches."},
                {"token": "one", "kind": "quantifier", "doc": "Exactly one element matches."},
                {"token": "all", "kind": "quantifier", "doc": "Every element matches (true when the list is empty)."},
                {"token": "is", "kind": "comparison", "doc": "Compares a field: `is_favorite is true`."},
                {"token": "true", "kind": "boolean", "doc": "A true boolean value."},
                {"token": "false", "kind": "boolean", "doc": "A false boolean value."},
            ],
            "operators": {name: dict(info, name=name) for name, info in OPERATORS.items()},
        },
        "quantifiers": [
            {"name": "any", "label": "has any", "doc": "At least one element matches the filter."},
            {"name": "none", "label": "has none", "doc": "No element matches the filter."},
            {"name": "one", "label": "has one", "doc": "Exactly one element matches the filter."},
            {"name": "all", "label": "has all", "doc": "Every element matches the filter."},
        ],
        "collections": [_collection_json(spec) for spec in COLLECTIONS],
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
    return FIELD_BY_PATH.get(path)


def collection_for(path: str) -> CollectionSpec | None:
    return COLLECTION_BY_PATH.get(path)


def element_for(spec: CollectionSpec, key: str) -> ElementSpec | None:
    for element in spec.elements:
        if element.key == key:
            return element

    return None


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

    value = walk(photo_view(photo), spec.source or spec.path)

    if value is MISSING or value is None:
        return value

    if spec.kind == "number":
        return as_number(value)

    if spec.kind == "list":
        return list(value) if isinstance(value, (list, tuple)) else value

    return value


def collection_values(photo: Photo, path: str) -> list[Any]:
    """The elements of a declared collection, or an empty list."""
    spec = collection_for(path)

    if spec is None:
        return []

    value = walk(photo_view(photo), spec.path)

    if value is MISSING or not isinstance(value, list):
        return []

    return value


def element_value(item: Any, element: ElementSpec) -> Any:
    """The value of one declared element key inside a collection element."""
    return walk(item, element.key)


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------


def _require_operand(
    label: str, kind: str, op: str, value: Any, low: float | None = None, high: float | None = None
) -> None:
    if op == "in":
        if not isinstance(value, list) or not value:
            raise RuleValidationError("'in' needs a list of values")

        values: list[Any] = value
    else:
        if value is None or value == "":
            raise RuleValidationError(f"'{label}' needs a value")

        values = [value]

    if kind == "number":
        for item in values:
            number = as_number(item)

            if number is None:
                raise RuleValidationError(f"'{label}' needs a number")

            if low is not None and high is not None and not low <= number <= high:
                raise RuleValidationError(f"'{label}' must be between {low:g} and {high:g}")

    if kind == "date":
        for item in values:
            try:
                date.fromisoformat(str(item))
            except ValueError as exception:
                raise RuleValidationError(f"'{label}' needs a YYYY-MM-DD date") from exception

    if kind == "bool" and not isinstance(value, bool):
        raise RuleValidationError(f"'{label}' needs true or false")


def _require_value(condition: ScalarCondition) -> None:
    spec = field_for(condition.path)

    if spec is None:
        raise RuleValidationError(f"Unknown metadata field: {condition.path}")

    if condition.op not in spec.operators:
        raise RuleValidationError(f"'{condition.op}' cannot be used on '{condition.path}'")

    _require_operand(condition.path, spec.kind, condition.op, condition.value)


def _require_element(condition: ElementCondition, collection: CollectionSpec) -> None:
    element = element_for(collection, condition.key)

    if element is None:
        raise RuleValidationError(f"Unknown {collection.path} key: {condition.key}")

    if condition.op not in element.operators:
        raise RuleValidationError(f"'{condition.op}' cannot be used on '{collection.path}.{condition.key}'")

    _require_operand(condition.key, element.kind, condition.op, condition.value, element.min, element.max)


def _count(conditions: list[Condition]) -> int:
    total = 0

    for condition in conditions:
        if condition.type == "group":
            total += _count(condition.conditions)
        elif condition.type == "collection":
            total += _count([condition.condition])
        else:
            total += 1

    return total


def _validate_conditions(
    conditions: list[Condition], depth: int, scope: str, collection: CollectionSpec | None = None
) -> None:
    if depth > MAX_GROUP_DEPTH:
        raise RuleValidationError(f"Groups can nest at most {MAX_GROUP_DEPTH} levels")

    if not conditions:
        raise RuleValidationError("Every rule and group needs at least one condition")

    for condition in conditions:
        if condition.type == "group":
            _validate_conditions(condition.conditions, depth + 1, scope, collection)

        elif condition.type == "collection":
            if scope != "root":
                raise RuleValidationError("Collections cannot be nested")

            spec = collection_for(condition.path)

            if spec is None:
                raise RuleValidationError(f"Unknown collection: {condition.path}")

            if condition.quantifier not in QUANTIFIERS:
                raise RuleValidationError(f"Unknown quantifier: {condition.quantifier}")

            _validate_conditions([condition.condition], depth + 1, "element", spec)

        elif condition.type == "element":
            if scope != "element" or collection is None:
                raise RuleValidationError("Element conditions only belong inside a collection filter")

            _require_element(condition, collection)

        else:
            if scope != "root":
                raise RuleValidationError("A collection filter compares element keys, not photo fields")

            _require_value(condition)


def validate_definition(definition: Definition) -> Definition:
    """Reject a definition whose paths, operators or values the schema does not allow."""
    if not definition.conditions:
        raise RuleValidationError("The rule needs at least one condition")

    if _count(definition.conditions) > MAX_CONDITIONS:
        raise RuleValidationError(f"A rule holds at most {MAX_CONDITIONS} conditions")

    _validate_conditions(definition.conditions, 0, "root")

    return definition


__all__ = [
    "ALTERNATIVES",
    "COLLECTIONS",
    "COLLECTION_BY_PATH",
    "FIELDS",
    "FIELD_BY_PATH",
    "GROUPS",
    "KIND_OPERATORS",
    "MAX_CONDITIONS",
    "MAX_GROUP_DEPTH",
    "NUMERIC_OPS",
    "OBJECTS",
    "OBJECT_LABELS",
    "OPERATORS",
    "PROCESSING",
    "QUANTIFIERS",
    "SCHEMA_VERSION",
    "CollectionSpec",
    "ElementSpec",
    "FieldSpec",
    "GroupSpec",
    "RuleValidationError",
    "as_number",
    "collection_for",
    "collection_values",
    "element_for",
    "element_value",
    "field_for",
    "resolve",
    "schema",
    "validate_definition",
]
