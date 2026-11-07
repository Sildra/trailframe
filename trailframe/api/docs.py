from __future__ import annotations

from importlib import resources

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/docs", tags=["docs"])

_DOCUMENTS: dict[str, tuple[str, str]] = {
    "hardware": ("Hardware & performance", "Memory requirements and heavy scanners"),
    "tutorial": ("Tutorial", "A short tour of Trailframe"),
    "whats-new": ("What's new", "Highlights from each release"),
}


class DocumentSummary(BaseModel):
    name: str
    title: str
    description: str


class Document(DocumentSummary):
    content: str


def _document_path(name: str):
    return resources.files("trailframe").joinpath("docs", f"{name}.md")


@router.get("", response_model=list[DocumentSummary])
async def list_documents() -> list[DocumentSummary]:
    return [
        DocumentSummary(name=name, title=title, description=description)
        for name, (title, description) in _DOCUMENTS.items()
    ]


@router.get("/{name}", response_model=Document)
async def get_document(name: str) -> Document:
    if name not in _DOCUMENTS:
        raise HTTPException(status_code=404, detail=f"Unknown document '{name}'")

    try:
        content = _document_path(name).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=404, detail=f"Document '{name}' not found") from exc

    title, description = _DOCUMENTS[name]
    return Document(name=name, title=title, description=description, content=content)
