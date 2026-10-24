"""Evaluate a parsed rule definition against a photo."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from trailframe.models.photo import Photo
from trailframe.services.rules.ast import Condition, Definition, DetectionCondition, ScalarCondition
from trailframe.services.rules.metadata import MISSING, as_float, detections
from trailframe.services.rules.schema import as_number, field_for, resolve


def tags_for_photo(photo: Photo, rules: Iterable[tuple[str, Definition]]) -> list[str]:
    """The tags every enabled rule assigns to `photo`, in rule order."""
    assigned: list[str] = []

    for tag, definition in rules:
        if tag and tag not in assigned and matches(photo, definition):
            assigned.append(tag)

    return assigned


def matches(photo: Photo, definition: Definition) -> bool:
    """Whether the photo satisfies the whole definition."""
    if not definition.conditions:
        return False

    results = [_matches_condition(photo, condition) for condition in definition.conditions]

    if definition.match == "any":
        return any(results)

    return all(results)


def _matches_condition(photo: Photo, condition: Condition) -> bool:
    if condition.type == "group":
        results = [_matches_condition(photo, child) for child in condition.conditions]

        return any(results) if condition.match == "any" else all(results)

    if condition.type == "detection":
        return _matches_detection(photo, condition)

    return _matches_scalar(photo, condition)


def _matches_scalar(photo: Photo, condition: ScalarCondition) -> bool:
    value = resolve(photo, condition.path)

    if value is MISSING:
        return False

    spec = field_for(condition.path)

    if spec is None:
        return False

    if value is None:
        return condition.op in ("neq", "not_contains")

    expected = condition.value

    if condition.op == "eq":
        return _equals(value, expected, spec.kind)
    if condition.op == "neq":
        return not _equals(value, expected, spec.kind)
    if condition.op == "contains":
        return _contains(value, expected)
    if condition.op == "not_contains":
        return not _contains(value, expected)
    if condition.op == "in":
        return any(_equals(value, item, spec.kind) for item in _list(expected))
    if condition.op in ("gt", "gte", "lt", "lte"):
        return _order(value, condition.op, expected, spec.kind)

    return False


def _matches_detection(photo: Photo, condition: DetectionCondition) -> bool:
    found = detections(photo, condition.label or None)

    if condition.op == "absent":
        return not found

    if not condition.label and not condition.metrics:
        return bool(photo.objects)

    if not found:
        return False

    if not condition.metrics:
        return True

    return any(
        all(_compare_metric(detection, metric.name, metric.op, metric.value) for metric in condition.metrics)
        for detection in found
    )


def _compare_metric(detection: dict[str, Any], name: str, op: str, expected: float) -> bool:
    value = detection.get(name)

    if value is None:
        return False

    return _order(value, op, expected, "number")


def _equals(value: Any, expected: Any, kind: str) -> bool:
    if kind == "number":
        left, right = as_number(value), as_number(expected)

        return left is not None and right is not None and left == right

    if kind == "bool":
        return bool(value) == bool(expected)

    if isinstance(value, list):
        return any(_equals(item, expected, "text") for item in value)

    if value is None or expected is None:
        return value is expected

    return _text(value) == _text(expected)


def _contains(value: Any, expected: Any) -> bool:
    if isinstance(value, list):
        return any(_text(expected) in _text(item) for item in value)

    if value is None or expected is None:
        return False

    return _text(expected) in _text(value)


def _order(value: Any, op: str, expected: Any, kind: str) -> bool:
    if kind == "number":
        left, right = as_number(value), as_number(expected)
    else:
        left, right = as_float(value), as_float(expected)

        if left is None or right is None:
            left, right = _text(value), _text(expected)

    if left is None or right is None:
        return False

    if op == "gt":
        return left > right
    if op == "gte":
        return left >= right
    if op == "lt":
        return left < right

    return left <= right


def _list(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple, set)):
        return list(value)

    return [value]


def _text(value: Any) -> str:
    return str(value).strip().casefold()


__all__ = ["matches", "tags_for_photo"]
