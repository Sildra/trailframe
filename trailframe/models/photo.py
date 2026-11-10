from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import DateTime
from sqlmodel import JSON, Column, Field, LargeBinary, SQLModel

from trailframe.models.photo_file import PhotoFile

# Naive datetimes, stored as-is. Plain `datetime` fields require tz-aware values on
# sqlmodel >= 0.0.48, while pydantic's NaiveDatetime is unmapped on sqlmodel < 0.0.44.
NAIVE_DATETIME = DateTime


class Photo(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)

    # The original archive file, relative to the originals folder.
    path: str = Field(index=True, unique=True)
    filename: str | None = Field(index=True)
    file_size: int | None = Field(index=True)
    date: datetime | None = Field(default=None, index=True, sa_type=NAIVE_DATETIME())
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
    objects: dict = Field(default_factory=dict, sa_column=Column(JSON))
    phash: bytes | None = Field(default=None, sa_column=Column(LargeBinary(8)))

    # Processed files, path relative to the processed folder. Each entry is plain
    # file data: {target_size, path, filename, file_size, width, height, main}.
    alternatives: list[dict] = Field(default_factory=list, sa_column=Column(JSON))

    # What preprocessing was applied, independently of the files it produced:
    # {step, source, target_size, format, quality, tool, tool_version, at}.
    processing: list[dict] = Field(default_factory=list, sa_column=Column(JSON))

    @property
    def original(self) -> PhotoFile:
        """The original archive file."""
        return PhotoFile(kind="original", path=self.path, filename=self.filename, file_size=self.file_size)

    def main(self) -> PhotoFile:
        """The alternative used by pipelines and the gallery, or the original when none is flagged."""
        for entry in self.alternatives or []:
            if entry.get("main"):
                return PhotoFile.from_alternative(entry)

        return self.original

    def alternative(self, target_size: int) -> PhotoFile | None:
        """The alternative generated for a target size, if any."""
        for entry in self.alternatives or []:
            if entry.get("target_size") == target_size:
                return PhotoFile.from_alternative(entry)

        return None


class GeoPoint(BaseModel):
    lat: float
    lon: float


class PhotoMap(BaseModel):
    width: int
    height: int
    zoom: float
    center: GeoPoint
    point: GeoPoint | None = None


class LocationEstimate(BaseModel):
    lat: float
    lon: float
    radius_m: float


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
    objects: dict = {}
    phash: str | None = None
    alternatives: list[dict] = []
    processing: list[dict] = []
    map: PhotoMap | None = None
    groups: list[RelatedPhotoGroup] = []
    location_estimate: LocationEstimate | None = None

    @staticmethod
    def from_photo(photo: "Photo", *, groups: list["RelatedPhotoGroup"] | None = None) -> "PhotoDetail":
        from trailframe.services.map.location_service import LocationService

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
            exif=photo.exif,
            tags=photo.tags or [],
            scores=photo.scores or {},
            scanners=photo.scanners or [],
            objects=photo.objects or {},
            phash=photo.phash.hex() if photo.phash else None,
            alternatives=photo.alternatives or [],
            processing=photo.processing or [],
            map=map_data,
            groups=groups or [],
        )
