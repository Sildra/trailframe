from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from trailframe.models.tag import TagNode
from trailframe.services.photos.tag_service import TagConflictError, TagService

router = APIRouter(prefix="/api/tags", tags=["tags"])


class TagPayload(BaseModel):
    """A tag as sent by the vocabulary editor."""

    id: int | None = None
    path: str
    description: str | None = None


class TagSyncRequest(BaseModel):
    """The complete vocabulary, as edited by the client."""

    tags: list[TagPayload]


class TagCreate(BaseModel):
    """A single tag to add to the vocabulary."""

    path: str
    description: str | None = None


class TagError(BaseModel):
    """The reason why a tag operation was refused."""

    detail: str


ERROR_RESPONSES = {
    400: {"model": TagError, "description": "The tag path is invalid"},
    404: {"model": TagError, "description": "The tag does not exist"},
    409: {"model": TagError, "description": "A tag already exists at that path"},
}


@router.get("", response_model=list[TagNode])
async def list_tags() -> list[TagNode]:
    return await TagService.get_tree()


@router.put("", response_model=list[TagNode], responses=ERROR_RESPONSES)
async def update_tags(payload: TagSyncRequest) -> list[TagNode]:
    try:
        await TagService.sync([entry.model_dump() for entry in payload.tags])
    except ValueError as exception:
        raise HTTPException(400, str(exception)) from exception

    return await TagService.get_tree()


@router.post("", response_model=list[TagNode], responses=ERROR_RESPONSES)
async def create_tag(payload: TagCreate) -> list[TagNode]:
    try:
        return await TagService.create(payload.path, payload.description)
    except TagConflictError as exception:
        raise HTTPException(409, str(exception)) from exception
    except ValueError as exception:
        raise HTTPException(400, str(exception)) from exception


@router.delete("/{tag_id}", responses=ERROR_RESPONSES)
async def delete_tag(tag_id: int) -> dict:
    result = await TagService.delete(tag_id)

    if result is None:
        raise HTTPException(404, f"Tag {tag_id} not found")

    return result
