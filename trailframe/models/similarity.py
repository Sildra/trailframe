from typing import Literal

from pydantic import BaseModel, Field

from trailframe.models.photo import PhotoDetail


class ImageSize(BaseModel):
    """Pixel dimensions of the image a fingerprint was measured on."""

    width: int
    height: int


class FingerprintMarker(BaseModel):
    """One fingerprint feature, in normalised image coordinates."""

    key: str
    label: str
    kind: Literal["object", "texture"]
    box: list[float] = Field(min_length=4, max_length=4)
    confidence: float = Field(ge=0, le=1)
    shared: bool = False


class Fingerprint(BaseModel):
    """The features used to compare a candidate with the seed photo."""

    method: Literal["objects", "texture"]
    reference: ImageSize
    markers: list[FingerprintMarker] = []


class SimilarPhoto(BaseModel):
    """A photo in the relative time window, scored against the seed photo."""

    photo: PhotoDetail
    similar: bool
    score: float = Field(ge=0, le=1)
    shared_objects: list[str] = []
    fingerprint: Fingerprint | None = None
