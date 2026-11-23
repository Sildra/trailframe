from pydantic import BaseModel, Field

from trailframe.models.photo import PhotoDetail


class SimilarPhoto(BaseModel):
    """A photo in the relative time window, scored against the seed photo."""

    photo: PhotoDetail
    similar: bool
    score: float = Field(ge=0, le=1)
    phash_distance: int | None = None
    shared_objects: list[str] = []
