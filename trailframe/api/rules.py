from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from trailframe.services.rules.ast import Definition
from trailframe.services.rules.rule_service import RuleService, RuleValidationError

router = APIRouter(prefix="/api/rules", tags=["rules"])


class RulePayload(BaseModel):
    """A rule as authored in the editor. The tag owns the rule."""

    tag: str
    name: str
    description: str = ""
    enabled: bool = True
    priority: int = 0
    expression: str = ""
    definition: Definition


class RuleResponse(RulePayload):
    """A stored rule, with its id and owning tag."""

    id: str


class RulePreviewRequest(BaseModel):
    """A draft rule to evaluate against the photos already in the library."""

    tag: str
    definition: Definition
    limit: int = 24


class RulePreviewPhoto(BaseModel):
    photo_id: int | None = None
    filename: str | None = None


class RulePreviewResponse(BaseModel):
    tag: str
    count: int
    truncated: bool = False
    photos: list[RulePreviewPhoto] = []


class RuleApplyResponse(BaseModel):
    photos: int
    changed: int
    added: int


ERROR_RESPONSES = {400: {"description": "The rule is malformed"}, 404: {"description": "The rule does not exist"}}


@router.get("/schema")
async def get_schema() -> dict[str, Any]:
    """The photo schema the editor renders, validates and hints from."""
    return RuleService.fields()


@router.get("/values")
async def get_values() -> dict[str, list[str]]:
    """Bounded value dictionaries for the editor's suggestions."""
    return await RuleService.values()


@router.get("", response_model=list[RuleResponse])
async def list_rules() -> list[dict[str, Any]]:
    return await RuleService.list()


@router.post("", response_model=RuleResponse, responses=ERROR_RESPONSES)
async def create_rule(payload: RulePayload) -> dict[str, Any]:
    try:
        return await RuleService.create(payload.model_dump())
    except RuleValidationError as exception:
        raise HTTPException(400, str(exception)) from exception


@router.post("/preview", response_model=RulePreviewResponse, responses=ERROR_RESPONSES)
async def preview_rule(payload: RulePreviewRequest) -> dict[str, Any]:
    """The photos a draft rule would tag; read-only."""
    try:
        return await RuleService.preview(payload.tag, payload.definition, payload.limit)
    except RuleValidationError as exception:
        raise HTTPException(400, str(exception)) from exception


@router.post("/apply", response_model=RuleApplyResponse)
async def apply_rules() -> dict[str, int]:
    """Apply every enabled rule to the photos already in the library."""
    return await RuleService.apply_all()


@router.get("/{rule_id}", response_model=RuleResponse, responses=ERROR_RESPONSES)
async def get_rule(rule_id: str) -> dict[str, Any]:
    rule = await RuleService.get(rule_id)

    if rule is None:
        raise HTTPException(404, f"Rule {rule_id} not found")

    return rule


@router.put("/{rule_id}", response_model=RuleResponse, responses=ERROR_RESPONSES)
async def update_rule(rule_id: str, payload: RulePayload) -> dict[str, Any]:
    try:
        rule = await RuleService.update(rule_id, payload.model_dump())
    except RuleValidationError as exception:
        raise HTTPException(400, str(exception)) from exception

    if rule is None:
        raise HTTPException(404, f"Rule {rule_id} not found")

    return rule


@router.delete("/{rule_id}", responses=ERROR_RESPONSES)
async def delete_rule(rule_id: str) -> dict:
    deleted = await RuleService.delete(rule_id)

    if not deleted:
        raise HTTPException(404, f"Rule {rule_id} not found")

    return {"deleted": True}
