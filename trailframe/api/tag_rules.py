from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from trailframe.models.tag_rule import TagRule
from trailframe.services.photos.tag_rule_service import TagRuleService

router = APIRouter(prefix="/api/tag-rules", tags=["tag-rules"])


class TagRulePayload(BaseModel):
    """A rule as edited in the assisted builder."""

    name: str
    enabled: bool = True
    priority: int = 0
    description: str | None = None
    conditions: dict = {}
    tags: list[str] = []


class TagRuleResponse(BaseModel):
    """A stored rule."""

    id: int | None = None
    name: str
    enabled: bool = True
    priority: int = 0
    description: str | None = None
    conditions: dict = {}
    tags: list[str] = []


class TagRuleField(BaseModel):
    """One metadata field the assisted builder offers."""

    field: str
    group: str
    label: str
    description: str
    kind: str
    label_field: str | None = None
    metrics: list[str] = []
    suggestions: list[str] = []
    operators: list[dict[str, str]] = []


class TagRuleTestRequest(BaseModel):
    """A draft rule to evaluate against the photos already in the library."""

    rule: TagRulePayload
    limit: int = 50


class TagRuleTestMatch(BaseModel):
    """One photo a draft rule matches, with the tags it would add."""

    photo_id: int | None = None
    filename: str | None = None
    tags: list[str] = []


class TagRuleApplyResponse(BaseModel):
    """The outcome of applying every enabled rule to the library."""

    photos: int
    changed: int
    added: int


ERROR_RESPONSES = {400: {"description": "The rule is malformed"}, 404: {"description": "The rule does not exist"}}


def _serialize(rule: TagRule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "name": rule.name,
        "enabled": rule.enabled,
        "priority": rule.priority,
        "description": rule.description,
        "conditions": rule.conditions or {},
        "tags": rule.tags or [],
    }


@router.get("/fields", response_model=list[TagRuleField])
async def list_fields() -> list[dict[str, Any]]:
    """The metadata catalog the assisted builder renders."""
    return TagRuleService.fields()


@router.get("", response_model=list[TagRuleResponse])
async def list_rules() -> list[dict[str, Any]]:
    rules = await TagRuleService.list()

    return [_serialize(rule) for rule in rules]


@router.post("", response_model=TagRuleResponse, responses=ERROR_RESPONSES)
async def create_rule(payload: TagRulePayload) -> dict[str, Any]:
    try:
        rule = await TagRuleService.create(payload.model_dump())
    except ValueError as exception:
        raise HTTPException(400, str(exception)) from exception

    return _serialize(rule)


@router.post("/test", response_model=list[TagRuleTestMatch], responses=ERROR_RESPONSES)
async def test_rule(payload: TagRuleTestRequest) -> list[dict[str, Any]]:
    try:
        return await TagRuleService.test_rule(payload.rule.model_dump(), payload.limit)
    except ValueError as exception:
        raise HTTPException(400, str(exception)) from exception


@router.post("/apply", response_model=TagRuleApplyResponse)
async def apply_rules() -> dict[str, int]:
    """Apply every enabled rule to the photos already in the library."""
    return await TagRuleService.apply_all()


@router.get("/{rule_id}", response_model=TagRuleResponse, responses=ERROR_RESPONSES)
async def get_rule(rule_id: int) -> dict[str, Any]:
    rule = await TagRuleService.get(rule_id)

    if rule is None:
        raise HTTPException(404, f"Rule {rule_id} not found")

    return _serialize(rule)


@router.put("/{rule_id}", response_model=TagRuleResponse, responses=ERROR_RESPONSES)
async def update_rule(rule_id: int, payload: TagRulePayload) -> dict[str, Any]:
    try:
        rule = await TagRuleService.update(rule_id, payload.model_dump())
    except ValueError as exception:
        raise HTTPException(400, str(exception)) from exception

    if rule is None:
        raise HTTPException(404, f"Rule {rule_id} not found")

    return _serialize(rule)


@router.delete("/{rule_id}", responses=ERROR_RESPONSES)
async def delete_rule(rule_id: int) -> dict:
    deleted = await TagRuleService.delete(rule_id)

    if not deleted:
        raise HTTPException(404, f"Rule {rule_id} not found")

    return {"deleted": True}
