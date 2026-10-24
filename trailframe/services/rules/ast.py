from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class MetricConstraint(BaseModel):
    """A numeric bound on one detection metric (`confidence`, `surface`)."""

    name: str
    op: Literal["eq", "neq", "gt", "gte", "lt", "lte"] = "gte"
    value: float


class ScalarCondition(BaseModel):
    """A comparison of one metadata field against a value."""

    type: Literal["scalar"] = "scalar"
    path: str
    op: str = "eq"
    value: str | float | bool | list[str] | None = None


class DetectionCondition(BaseModel):
    """A detected object, optionally bound to one label and numeric metrics.

    The label and its metrics apply to the *same* detection.
    """

    type: Literal["detection"] = "detection"
    label: str = ""
    op: Literal["present", "absent"] = "present"
    metrics: list[MetricConstraint] = Field(default_factory=list)


class GroupCondition(BaseModel):
    """A nested `all`/`any` group of conditions."""

    type: Literal["group"] = "group"
    match: Literal["all", "any"] = "all"
    conditions: list[Condition] = Field(default_factory=list)


Condition = Annotated[ScalarCondition | DetectionCondition | GroupCondition, Field(discriminator="type")]


class Definition(BaseModel):
    """The parsed form of a rule expression; the authoritative rule body."""

    version: int = 1
    match: Literal["all", "any"] = "all"
    conditions: list[Condition] = Field(default_factory=list)


GroupCondition.model_rebuild()

__all__ = ["Condition", "Definition", "DetectionCondition", "GroupCondition", "MetricConstraint", "ScalarCondition"]
