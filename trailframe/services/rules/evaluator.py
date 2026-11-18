"""Evaluate a parsed rule definition against a photo."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from trailframe.models.photo import Photo
from trailframe.services.rules.ast import CollectionCondition, Condition, Definition, ElementCondition, ScalarCondition
from trailframe.services.rules.metadata import MISSING, as_float
from trailframe.services.rules.schema import (
    CollectionSpec,
    as_number,
    collection_for,
    collection_values,
    element_for,
    element_value,
    field_for,
    resolve,
)


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
        return _matches_group(condition.match, condition.conditions, lambda child: _matches_condition(photo, child))

    if condition.type == "collection":
        return _matches_collection(photo, condition)

    if condition.type == "element":
        # Element conditions are only meaningful inside a collection filter.
        return False

    return _matches_scalar(photo, condition)


def _matches_group(match: str, conditions: list[Condition], evaluate) -> bool:
    results = [evaluate(condition) for condition in conditions]

    return any(results) if match == "any" else all(results)


def _matches_scalar(photo: Photo, condition: ScalarCondition) -> bool:
    value = resolve(photo, condition.path)

    if value is MISSING:
        return False

    spec = field_for(condition.path)

    if spec is None:
        return False

    return _compare(value, condition.op, condition.value, spec.kind)


def _matches_collection(photo: Photo, condition: CollectionCondition) -> bool:
    spec = collection_for(condition.path)

    if spec is None:
        return False

    results = [_matches_element(item, condition.condition, spec) for item in collection_values(photo, condition.path)]

    if condition.quantifier == "any":
        return any(results)

    if condition.quantifier == "none":
        return not any(results)

    if condition.quantifier == "one":
        return sum(1 for result in results if result) == 1

    # `all` is vacuously true on an empty collection.
    return all(results)


def _matches_element(item: Any, condition: Condition, spec: CollectionSpec) -> bool:
    if condition.type == "group":
        return _matches_group(condition.match, condition.conditions, lambda child: _matches_element(item, child, spec))

    if condition.type != "element":
        return False

    return _matches_element_condition(item, condition, spec)


def _matches_element_condition(item: Any, condition: ElementCondition, spec: CollectionSpec) -> bool:
    element = element_for(spec, condition.key)

    if element is None:
        return False

    value = element_value(item, element)

    if value is MISSING or value is None:
        return condition.op in ("neq", "not_contains")

    expected = condition.value

    if element.kind == "number":
        number = as_number(value)
        bound = as_number(expected)

        if number is None or bound is None:
            return False

        value = number
        expected = bound

    return _compare(value, condition.op, expected, element.kind)


def _compare(value: Any, op: str, expected: Any, kind: str) -> bool:
    if value is None:
        return op in ("neq", "not_contains")

    if op == "eq":
        return _equals(value, expected, kind)
    if op == "neq":
        return not _equals(value, expected, kind)
    if op == "contains":
        return _contains(value, expected)
    if op == "not_contains":
        return not _contains(value, expected)
    if op == "in":
        return any(_equals(value, item, kind) for item in _list(expected))
    if op in ("gt", "gte", "lt", "lte"):
        return _order(value, op, expected, kind)

    return False


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
