from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlmodel import select

from trailframe.models.activity import Activity, coerce_trace
from trailframe.models.photo import Photo
from trailframe.services.core.database_service import DatabaseService

router = APIRouter(prefix="/api/map-data", tags=["map-data"])


class PhotoPoint(BaseModel):
    id: int
    lat: float
    lon: float


class ActivityTrace(BaseModel):
    id: int
    name: str | None
    trace: list[list[float]]
    start_time: datetime | None = None
    distance: float | None = None
    duration: float | None = None


class MapData(BaseModel):
    photos: list[PhotoPoint]
    activities: list[ActivityTrace]


@router.get("", response_model=MapData)
async def get_map_data() -> MapData:
    async def _query(session) -> MapData:
        photo_rows = (
            await session.execute(
                select(Photo.id, Photo.latitude, Photo.longitude).where(
                    Photo.latitude.is_not(None), Photo.longitude.is_not(None)
                )
            )
        ).all()

        activity_rows = (
            await session.execute(
                select(
                    Activity.id,
                    Activity.name,
                    Activity.trace,
                    Activity.start_time,
                    Activity.distance,
                    Activity.duration,
                )
            )
        ).all()

        return MapData(
            photos=[PhotoPoint(id=p[0], lat=p[1], lon=p[2]) for p in photo_rows],
            activities=[
                ActivityTrace(
                    id=a[0],
                    name=a[1],
                    trace=[[pt[1], pt[2]] for pt in coerce_trace(a[2]) if len(pt) > 2],
                    start_time=a[3],
                    distance=a[4],
                    duration=a[5],
                )
                for a in activity_rows
                if a[2]
            ],
        )

    return await DatabaseService.execute(_query)
