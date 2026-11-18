from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

ScalarValue = str | float | bool | list[str] | None


class ElementCondition(BaseModel):
    """One key/value comparison inside a collection filter (`confidence >= 80`).

    Element conditions only make sense inside a `CollectionCondition`; the key
    is declared by the collection spec, not by the photo's columns.
    """

    type: Literal["element"] = "element"
    key: str
    op: str = "eq"
    value: ScalarValue = None


class ScalarCondition(BaseModel):
    """A comparison of one metadata field against a value."""

    type: Literal["scalar"] = "scalar"
    path: str
    op: str = "eq"
    value: ScalarValue = None


class CollectionCondition(BaseModel):
    """A quantified filter over a multi-valued field: `objects[label=dog] has any`.

    `condition` is a boolean expression in *element scope*: its leaves are
    `ElementCondition`s, so every constraint binds to the same element.
    """

    type: Literal["collection"] = "collection"
    path: str
    quantifier: Literal["any", "none", "one", "all"] = "any"
    condition: Condition


class GroupCondition(BaseModel):
    """A nested `all`/`any` group of conditions."""

    type: Literal["group"] = "group"
    match: Literal["all", "any"] = "all"
    conditions: list[Condition] = Field(default_factory=list)


Condition = Annotated[
    ScalarCondition | CollectionCondition | ElementCondition | GroupCondition, Field(discriminator="type")
]


class Definition(BaseModel):
    """The parsed form of a rule expression; the authoritative rule body."""

    version: int = 2
    match: Literal["all", "any"] = "all"
    conditions: list[Condition] = Field(default_factory=list)


GroupCondition.model_rebuild()
CollectionCondition.model_rebuild()

__all__ = [
    "CollectionCondition",
    "Condition",
    "Definition",
    "ElementCondition",
    "GroupCondition",
    "ScalarCondition",
    "ScalarValue",
]
