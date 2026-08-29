import mimetypes
import random
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select, text

from trailframe.models.group import PhotoGroup, PhotoGroupSummary
from trailframe.models.photo import Photo, PhotoDetail, RelatedPhotoGroup
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.map.location_service import LocationService
from trailframe.services.photos.folder_service import FolderService
from trailframe.services.photos.photo_service import PhotoService
from trailframe.services.photos.thumbnail_service import ThumbnailService

router = APIRouter(prefix="/api/photos", tags=["photos"])


class PhotoGroupCreate(BaseModel):
    name: str
    start_date: date
    end_date: date


class FavoriteUpdate(BaseModel):
    value: bool


def _group_date_bounds(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    return (datetime.combine(start_date, time.min), datetime.combine(end_date + timedelta(days=1), time.min))


@router.get("", response_model=list[PhotoDetail])
async def list_photos(favorites: bool = Query(False)) -> list[PhotoDetail]:
    async def _list(session) -> list[PhotoDetail]:
        stmt = select(Photo).order_by(Photo.date.asc().nulls_last(), Photo.id.asc())

        if favorites:
            stmt = stmt.where(Photo.is_favorite)

        result = await session.execute(stmt)

        return [PhotoDetail.from_photo(photo) for photo in result.scalars().all()]

    return await DatabaseService.execute(_list)


@router.get("/favorites", response_model=list[int])
async def list_favorite_ids() -> list[int]:
    async def _list(session) -> list[int]:
        result = await session.execute(
            select(Photo.id).where(Photo.is_favorite).order_by(Photo.date.asc().nulls_last(), Photo.id.asc())
        )

        return list(result.scalars().all())

    return await DatabaseService.execute(_list)


@router.get("/custom", response_model=list[int])
async def custom_slideshow(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    group: str | None = Query(None),
    location: str | None = Query(None),
    tags: list[str] | None = Query(None),
    favorites: bool = Query(False),
    randomize: bool = Query(False),
) -> list[int]:
    async def _query(session) -> list[int]:
        stmt = select(Photo.id)

        if start_date is not None:
            stmt = stmt.where(Photo.date >= datetime.combine(start_date, time.min))

        if end_date is not None:
            stmt = stmt.where(Photo.date < datetime.combine(end_date + timedelta(days=1), time.min))

        if favorites:
            stmt = stmt.where(Photo.is_favorite)

        if group is not None:
            group_row = (await session.execute(select(PhotoGroup).where(PhotoGroup.name == group))).scalar_one_or_none()

            if group_row is not None and group_row.start_date is not None and group_row.end_date is not None:
                start, end = _group_date_bounds(group_row.start_date, group_row.end_date)
                stmt = stmt.where(Photo.date >= start, Photo.date < end)
            else:
                return []

        if location is not None:
            pattern = f"%{location}%"
            stmt = stmt.where(Photo.location.ilike(pattern))

        if tags is not None:
            for tag in tags:
                stmt = stmt.where(Photo.tags.ilike(f"%{tag}%"))

        result = await session.execute(stmt.order_by(Photo.date.asc().nulls_last(), Photo.id.asc()))
        photo_ids = list(result.scalars().all())

        if randomize:
            photo_ids = random.sample(photo_ids, len(photo_ids))

        return photo_ids

    return await DatabaseService.execute(_query)


@router.get("/count")
async def get_photo_count() -> int:
    async def _count(session) -> int:
        result = await session.execute(select(func.count()).select_from(Photo))
        return result.scalar_one()

    return await DatabaseService.execute(_count)


@router.get("/groups", response_model=list[PhotoGroupSummary])
async def list_groups() -> list[PhotoGroupSummary]:
    async def _groups(session) -> list[PhotoGroupSummary]:
        group_rows = await session.execute(select(PhotoGroup).order_by(PhotoGroup.start_date.asc()))
        user_groups = list(group_rows.scalars().all())

        photo_result = await session.execute(
            select(Photo.id, Photo.date).order_by(Photo.date.asc().nulls_last(), Photo.id.asc())
        )
        photo_rows = list(photo_result.all())

        groups: list[PhotoGroupSummary] = []
        assigned_ids: set[int] = set()

        for group in user_groups:
            if group.start_date is None or group.end_date is None:
                continue

            start, end = _group_date_bounds(group.start_date, group.end_date)
            photo_ids = [
                photo_id for photo_id, photo_date in photo_rows if photo_date is not None and start <= photo_date < end
            ]
            assigned_ids.update(photo_ids)

            groups.append(
                PhotoGroupSummary(
                    id=group.id,
                    name=group.name,
                    start_date=group.start_date,
                    end_date=group.end_date,
                    automatic=False,
                    photo_ids=photo_ids,
                )
            )

        by_year: dict[int, list[int]] = {}
        undated: list[int] = []

        for photo_id, photo_date in photo_rows:
            if photo_id in assigned_ids:
                continue

            if photo_date is None:
                undated.append(photo_id)
            else:
                by_year.setdefault(photo_date.year, []).append(photo_id)

        for year in sorted(by_year):
            groups.append(
                PhotoGroupSummary(
                    name=str(year),
                    start_date=date(year, 1, 1),
                    end_date=date(year, 12, 31),
                    automatic=True,
                    photo_ids=by_year[year],
                )
            )

        if undated:
            groups.append(PhotoGroupSummary(name="No date", automatic=True, photo_ids=undated))

        groups.sort(key=lambda group: group.name)

        return groups

    return await DatabaseService.execute(_groups)


@router.post("/groups", response_model=PhotoGroupSummary)
async def create_group(payload: PhotoGroupCreate) -> PhotoGroupSummary:
    async def _create(session) -> PhotoGroupSummary:
        group = PhotoGroup(name=payload.name, start_date=payload.start_date, end_date=payload.end_date)

        session.add(group)
        await session.commit()
        await session.refresh(group)

        start, end = _group_date_bounds(payload.start_date, payload.end_date)
        result = await session.execute(
            select(Photo.id).where(Photo.date >= start, Photo.date < end).order_by(Photo.date.asc(), Photo.id.asc())
        )

        return PhotoGroupSummary(
            id=group.id,
            name=group.name,
            start_date=group.start_date,
            end_date=group.end_date,
            automatic=False,
            photo_ids=list(result.scalars().all()),
        )

    return await DatabaseService.execute(_create)


@router.delete("/groups/{group_id}")
async def delete_group(group_id: int):
    async def _delete(session):
        group = await session.get(PhotoGroup, group_id)

        if group is None:
            raise HTTPException(404, f"Group {group_id} not found")

        await session.delete(group)
        await session.commit()

        return {"deleted": True}

    return await DatabaseService.execute(_delete)


@router.delete("/{photo_id}")
async def delete_photo(photo_id: int):
    async def _delete(session):
        photo = (await session.execute(select(Photo).where(Photo.id == photo_id))).scalar_one_or_none()

        if photo is None:
            raise HTTPException(404, f"Photo {photo_id} not found")

        PhotoService.delete(photo)

        for size in ThumbnailService.sizes():
            thumbnail_path = ThumbnailService.get_thumbnail_path(photo, size)

            if thumbnail_path.exists():
                thumbnail_path.unlink()

        await session.delete(photo)
        await session.commit()

        return {"deleted": True}

    return await DatabaseService.execute(_delete)


@router.put("/{photo_id}/favorite")
async def set_favorite(photo_id: int, payload: FavoriteUpdate):
    async def _set(session):
        photo = (await session.execute(select(Photo).where(Photo.id == photo_id))).scalar_one_or_none()

        if photo is None:
            raise HTTPException(404, f"Photo {photo_id} not found")

        photo.is_favorite = payload.value
        await session.commit()

        return {"id": photo_id, "is_favorite": payload.value}

    return await DatabaseService.execute(_set)


@router.get("/{photo_id}/data", response_model=PhotoDetail)
async def get_photo(photo_id: int) -> PhotoDetail:
    async def _get(session) -> PhotoDetail:
        photo = (await session.execute(select(Photo).where(Photo.id == photo_id))).scalar_one_or_none()

        if photo is None:
            raise HTTPException(404, f"Photo {photo_id} not found")

        groups = []

        if photo.phash is not None:
            threshold = 8

            result = await session.execute(
                select(Photo.id).where(
                    Photo.id != photo_id,
                    Photo.phash.isnot(None),
                    text("hamming(photo.phash, :phash) < :threshold").bindparams(
                        phash=photo.phash, threshold=threshold
                    ),
                )
            )

            similar_ids = [row[0] for row in result.all()]

            if similar_ids:
                groups.append(RelatedPhotoGroup(name="Similar", photo_ids=similar_ids))

        return PhotoDetail.from_photo(photo, groups=groups)

    return await DatabaseService.execute(_get)


@router.get("/{photo_id}/image")
async def get_image(photo_id: int):
    async def _get(session):
        photo = (await session.execute(select(Photo).where(Photo.id == photo_id))).scalar_one_or_none()

        if photo is None:
            raise HTTPException(404, f"Photo {photo_id} not found")

        return photo

    photo = await DatabaseService.execute(_get)

    source = PhotoService.resolve(photo)
    media_type, _ = mimetypes.guess_type(source.name)
    return FileResponse(source, media_type=media_type)


@router.get("/{photo_id}/thumbnail")
async def get_thumbnail(photo_id: int, size: int | None = Query(None)):
    async def _get(session):
        photo = (await session.execute(select(Photo).where(Photo.id == photo_id))).scalar_one_or_none()

        if photo is None:
            raise HTTPException(404, f"Photo {photo_id} not found")

        return photo

    photo = await DatabaseService.execute(_get)

    target = ThumbnailService.select_size(size)
    thumbnail_path = ThumbnailService.get_thumbnail_path(photo, target)

    if not thumbnail_path.exists():
        thumbnail_path = ThumbnailService.generate(photo, target)

    return FileResponse(thumbnail_path, media_type="image/webp")


@router.get("/{photo_id}/wireframe")
async def get_wireframe(photo_id: int):
    async def _get(session):
        photo = (await session.execute(select(Photo).where(Photo.id == photo_id))).scalar_one_or_none()

        if photo is None:
            raise HTTPException(404, f"Photo {photo_id} not found")

        return photo

    photo = await DatabaseService.execute(_get)

    path = LocationService.get_wireframe_path(photo)

    if path is None:
        raise HTTPException(404, f"No wireframe for photo {photo_id}")

    return FileResponse(path, media_type="image/svg+xml")


@router.post("/upload")
async def upload_photo(file: UploadFile = File(...)):
    path = await FolderService.upload(file.filename, file)

    return {"filename": file.filename, "path": str(path)}
