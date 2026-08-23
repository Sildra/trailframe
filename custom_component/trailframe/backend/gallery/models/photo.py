from datetime import datetime

from pydantic import BaseModel
from sqlmodel import JSON, Column, Field, LargeBinary, SQLModel


class Photo(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)

    path: str = Field(index=True, unique=True)
    filename: str | None = Field(index=True)
    file_size: int | None = Field(index=True)
    date: datetime | None = Field(index=True)
    source: str | None = None
    is_favorite: bool = Field(default=False)
    latitude: float | None = None
    longitude: float | None = None
    location_source: str | None = None
    country: str | None = None
    location: str | None = None
    wireframe: str | None = None
    exif: dict = Field(default_factory=dict, sa_column=Column(JSON))
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    scores: dict = Field(default_factory=dict, sa_column=Column(JSON))
    scanners: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    objects: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    phash: bytes | None = Field(default=None, sa_column=Column(LargeBinary(8)))


class GeoPoint(BaseModel):
    lat: float
    lon: float


class PhotoMap(BaseModel):
    width: int
    height: int
    zoom: float
    center: GeoPoint
    point: GeoPoint | None = None


class RelatedPhotoGroup(BaseModel):
    name: str
    photo_ids: list[int] = []


class PhotoDetail(BaseModel):
    id: int | None = None
    path: str
    filename: str | None = None
    file_size: int | None = None
    date: datetime | None = None
    source: str | None = None
    is_favorite: bool = False
    latitude: float | None = None
    longitude: float | None = None
    country: str | None = None
    location: str | None = None
    wireframe: str | None = None
    exif: dict = {}
    tags: list[str] = []
    scores: dict = {}
    scanners: list[str] = []
    objects: list[dict] = []
    phash: str | None = None
    map: PhotoMap | None = None
    groups: list[RelatedPhotoGroup] = []

    @staticmethod
    def from_photo(photo: "Photo", *, groups: list["RelatedPhotoGroup"] | None = None) -> "PhotoDetail":
        from gallery.services.location_service import LocationService

        exif = {key: value for key, value in (photo.exif or {}).items() if key != "MakerNote"}

        map_data = None

        if photo.latitude is not None and photo.longitude is not None:
            wireframe_data = LocationService.get_wireframe_data(photo)

            if wireframe_data is not None:
                try:
                    map_data = PhotoMap(**wireframe_data)
                except (TypeError, ValueError):
                    map_data = None
                else:
                    map_data.point = GeoPoint(lat=photo.latitude, lon=photo.longitude)

        return PhotoDetail(
            id=photo.id,
            path=photo.path,
            filename=photo.filename,
            file_size=photo.file_size,
            date=photo.date,
            source=photo.source,
            is_favorite=bool(photo.is_favorite),
            latitude=photo.latitude,
            longitude=photo.longitude,
            country=photo.country,
            location=photo.location,
            wireframe=photo.wireframe,
            exif=exif,
            tags=photo.tags or [],
            scores=photo.scores or {},
            scanners=photo.scanners or [],
            objects=photo.objects or [],
            phash=photo.phash.hex() if photo.phash else None,
            map=map_data,
            groups=groups or [],
        )
