from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from gallery.models.activity import Activity
from gallery.models.photo import Photo
from gallery.services.database_service import DatabaseService

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
async def get_map_data(session: AsyncSession = Depends(DatabaseService.get_session)) -> MapData:
    photo_rows = (
        await session.execute(
            select(Photo.id, Photo.latitude, Photo.longitude).where(
                Photo.latitude.is_not(None), Photo.longitude.is_not(None)
            )
        )
    ).all()

    activity_rows = (
        await session.execute(select(Activity.id, Activity.name, Activity.trace, Activity.start_time, Activity.distance, Activity.duration))
    ).all()

    return MapData(
        photos=[PhotoPoint(id=p[0], lat=p[1], lon=p[2]) for p in photo_rows],
        activities=[
            ActivityTrace(
                id=a[0],
                name=a[1],
                trace=[[pt["lat"], pt["lon"]] for pt in (a[2] or []) if "lat" in pt and "lon" in pt],
                start_time=a[3],
                distance=a[4],
                duration=a[5],
            )
            for a in activity_rows
            if a[2]
        ],
    )
