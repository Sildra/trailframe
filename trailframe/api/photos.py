import mimetypes
import random
from datetime import date, datetime, time, timedelta
from io import BytesIO

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image, ImageOps
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text

from trailframe.models.group import PhotoGroup, PhotoGroupSummary
from trailframe.models.photo import Photo, PhotoDetail, RelatedPhotoGroup
from trailframe.models.similarity import SimilarPhoto
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.core.thread_pool_service import ThreadPoolService
from trailframe.services.map.location_service import LocationService
from trailframe.services.photos.duplicates_service import DuplicatesService
from trailframe.services.photos.folder_service import FolderService
from trailframe.services.photos.photo_service import PhotoService
from trailframe.services.photos.processing_service import ProcessingService, ReprocessError
from trailframe.services.photos.similarity_service import SimilarityError, SimilarityService
from trailframe.services.photos.tag_service import TagService
from trailframe.services.photos.thumbnail_service import ThumbnailService
from trailframe.services.processors import PROCESSOR_OVERRIDES
from trailframe.services.processors.tilt_processor import TiltOverride

router = APIRouter(prefix="/api/photos", tags=["photos"])


class PhotoGroupCreate(BaseModel):
    name: str
    start_date: date
    end_date: date


class FavoriteUpdate(BaseModel):
    value: bool


class PhotoTagsUpdate(BaseModel):
    tags: list[str]


class PhotoTagsResponse(BaseModel):
    id: int
    tags: list[str]


class ReprocessTilt(BaseModel):
    mode: str = "auto"
    angle: float | None = None
    crop_mode: str | None = None


class ReprocessExposure(BaseModel):
    enabled: bool | None = None
    exposure: float | None = None
    gamma: float | None = None


class ReprocessWhiteBalance(BaseModel):
    enabled: bool | None = None
    method: str | None = None
    strength: float | None = None
    temperature: float | None = None
    tint: float | None = None


class ReprocessContrast(BaseModel):
    enabled: bool | None = None
    method: str | None = None
    strength: float | None = None
    low_percentile: float | None = None
    high_percentile: float | None = None


class ReprocessLocalContrast(BaseModel):
    enabled: bool | None = None
    clip_limit: float | None = None
    tile_grid: int | None = None
    strength: float | None = None


class ReprocessVibrance(BaseModel):
    enabled: bool | None = None
    strength: float | None = None


class ReprocessNoiseReduction(BaseModel):
    enabled: bool | None = None
    method: str | None = None
    radius: int | None = None
    sigma_color: float | None = None
    sigma_space: float | None = None
    strength: float | None = None


class ReprocessSharpening(BaseModel):
    enabled: bool | None = None
    radius: float | None = None
    amount: float | None = None
    threshold: float | None = None


class ReprocessRequest(BaseModel):
    """Per-photo overrides; omitted fields keep the current/configured values."""

    alternatives: list[int] | None = None
    main: int | None = None
    tilt: ReprocessTilt | None = None
    exposure: ReprocessExposure | None = None
    white_balance: ReprocessWhiteBalance | None = None
    contrast: ReprocessContrast | None = None
    local_contrast: ReprocessLocalContrast | None = None
    vibrance: ReprocessVibrance | None = None
    noise_reduction: ReprocessNoiseReduction | None = None
    sharpening: ReprocessSharpening | None = None
    rescan: bool = True


class SimilarCandidatesRequest(BaseModel):
    """A relative capture-time window around one seed photo."""

    photo_id: int
    window_seconds: int = Field(default=3600, ge=1, le=30 * 24 * 3600)
    max_hamming: int = Field(default=12, ge=0, le=64)
    min_object_overlap: float = Field(default=0.4, ge=0, le=1)


class BatchReprocessRequest(BaseModel):
    """Apply one set of overrides to several photos."""

    photo_ids: list[int] = Field(min_length=1, max_length=100)
    options: ReprocessRequest


class BatchReprocessResult(BaseModel):
    photo_id: int
    photo: PhotoDetail | None = None
    error: str | None = None


def _group_date_bounds(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    return (datetime.combine(start_date, time.min), datetime.combine(end_date + timedelta(days=1), time.min))


def _tag_paths(tags: list[str] | None) -> list[str]:
    """Normalized tag paths, dropping the empty ones."""
    paths: list[str] = []

    for tag in tags or []:
        value = TagService.normalize(tag)

        if value and value not in paths:
            paths.append(value)

    return paths


def _build_reprocess_overrides(payload: ReprocessRequest) -> dict:
    """Translate a reprocess payload into typed processor overrides."""

    overrides = {}

    if payload.tilt is not None:
        mode = payload.tilt.mode.lower()

        if mode not in {"auto", "off", "manual"}:
            raise HTTPException(400, f"Unknown tilt mode '{payload.tilt.mode}'")

        if mode == "manual" and payload.tilt.angle is None:
            raise HTTPException(400, "A manual angle is required")

        overrides["Tilt"] = TiltOverride(
            enabled=mode != "off",
            angle=payload.tilt.angle if mode == "manual" else None,
            crop_mode=payload.tilt.crop_mode,
        )

    corrections = {
        "Exposure": payload.exposure,
        "White balance": payload.white_balance,
        "Contrast": payload.contrast,
        "Local contrast": payload.local_contrast,
        "Vibrance": payload.vibrance,
        "Noise reduction": payload.noise_reduction,
        "Sharpening": payload.sharpening,
    }

    for name, model in corrections.items():
        if model is not None:
            overrides[name] = PROCESSOR_OVERRIDES[name](**model.model_dump(exclude_none=True))

    return overrides


@router.get("", response_model=list[PhotoDetail])
async def list_photos(
    favorites: bool = Query(False),
    tags: list[str] | None = Query(None),
    tags_mode: str = Query("any", pattern="^(any|all)$"),
    include_descendants: bool = Query(True),
) -> list[PhotoDetail]:
    paths = _tag_paths(tags)

    async def _list(session) -> list[PhotoDetail]:
        stmt = select(Photo).order_by(Photo.date.asc().nulls_last(), Photo.id.asc())

        if favorites:
            stmt = stmt.where(Photo.is_favorite)

        if paths:
            condition = (
                TagService.match(paths, tags_mode) if include_descendants else TagService.match_exact(paths, tags_mode)
            )
            stmt = stmt.where(condition)

        result = await session.execute(stmt)

        return [PhotoDetail.from_photo(photo) for photo in result.scalars().all()]

    return await DatabaseService.execute(_list)


@router.get("/ids", response_model=list[int])
async def list_photo_ids(
    favorites: bool = Query(False),
    tags: list[str] | None = Query(None),
    tags_mode: str = Query("any", pattern="^(any|all)$"),
    include_descendants: bool = Query(True),
) -> list[int]:
    """The ids of the photos matching the given filters."""
    paths = _tag_paths(tags)

    async def _list(session) -> list[int]:
        stmt = select(Photo.id).order_by(Photo.date.asc().nulls_last(), Photo.id.asc())

        if favorites:
            stmt = stmt.where(Photo.is_favorite)

        if paths:
            condition = (
                TagService.match(paths, tags_mode) if include_descendants else TagService.match_exact(paths, tags_mode)
            )
            stmt = stmt.where(condition)

        result = await session.execute(stmt)

        return list(result.scalars().all())

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
            paths = _tag_paths(tags)

            if paths:
                stmt = stmt.where(TagService.match(paths, "all"))

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


@router.get("/duplicates", response_model=list[PhotoGroupSummary])
async def get_duplicates() -> list[PhotoGroupSummary]:
    clusters = await DuplicatesService.get_clusters()

    return [PhotoGroupSummary(name=f"Duplicate {ids[0]}", automatic=True, photo_ids=ids) for ids in clusters]


@router.get("/location-issues", response_model=list[PhotoGroupSummary])
async def get_location_issues() -> list[PhotoGroupSummary]:
    return await LocationService.get_groups()


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


@router.post("/similar-candidates", response_model=list[SimilarPhoto])
async def similar_candidates(payload: SimilarCandidatesRequest) -> list[SimilarPhoto]:
    """List photos in a relative time window, flagging object/phash matches."""

    try:
        return await SimilarityService.candidates(
            payload.photo_id, payload.window_seconds, payload.max_hamming, payload.min_object_overlap
        )
    except SimilarityError as error:
        raise HTTPException(error.status_code, str(error)) from error


@router.post("/reprocess-batch", response_model=list[BatchReprocessResult])
async def reprocess_batch(payload: BatchReprocessRequest) -> list[BatchReprocessResult]:
    """Apply one set of processing overrides to a selection of photos."""

    overrides = _build_reprocess_overrides(payload.options)
    results: list[BatchReprocessResult] = []

    for photo_id in payload.photo_ids:
        try:
            await ProcessingService.reprocess(
                photo_id,
                alternatives=payload.options.alternatives,
                main_target=payload.options.main,
                overrides=overrides,
                rescan=payload.options.rescan,
            )
            results.append(BatchReprocessResult(photo_id=photo_id, photo=await get_photo(photo_id)))
        except ReprocessError as error:
            results.append(BatchReprocessResult(photo_id=photo_id, error=str(error)))
        except HTTPException as error:
            results.append(BatchReprocessResult(photo_id=photo_id, error=str(error.detail)))

    return results


@router.delete("/{photo_id}")
async def delete_photo(photo_id: int):
    async def _fetch(session) -> Photo | None:
        return (await session.execute(select(Photo).where(Photo.id == photo_id))).scalar_one_or_none()

    photo = await DatabaseService.execute(_fetch)

    if photo is None:
        raise HTTPException(404, f"Photo {photo_id} not found")

    PhotoService.delete(photo)
    ThumbnailService.delete(photo)

    async def _delete(session):
        stored = (await session.execute(select(Photo).where(Photo.id == photo_id))).scalar_one()
        await session.delete(stored)
        await session.commit()
        DuplicatesService.mark_deleted(photo_id)
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


@router.put("/{photo_id}/tags", response_model=PhotoTagsResponse)
async def set_photo_tags(photo_id: int, payload: PhotoTagsUpdate):
    """Replace the tags of a photo with the given list."""
    tags = await TagService.set_photo_tags(photo_id, payload.tags)

    if tags is None:
        raise HTTPException(404, f"Photo {photo_id} not found")

    return {"id": photo_id, "tags": tags}


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
                    text("hamming(photos.phash, :phash) < :threshold").bindparams(
                        phash=photo.phash, threshold=threshold
                    ),
                )
            )

            similar_ids = [row[0] for row in result.all()]

            if similar_ids:
                groups.append(RelatedPhotoGroup(name="Similar", photo_ids=similar_ids))

        if photo.latitude is not None and photo.longitude is not None:
            near_distance = 500
            near_delta_lat = 0.005
            near_delta_lon = 0.005

            result = await session.execute(
                select(Photo.id, Photo.latitude, Photo.longitude).where(
                    Photo.id != photo_id,
                    Photo.latitude.isnot(None),
                    Photo.longitude.isnot(None),
                    Photo.latitude.between(photo.latitude - near_delta_lat, photo.latitude + near_delta_lat),
                    Photo.longitude.between(photo.longitude - near_delta_lon, photo.longitude + near_delta_lon),
                )
            )

            near = []
            for row in result.all():
                distance = LocationService.haversine(photo.latitude, photo.longitude, row[1], row[2])
                if distance <= near_distance:
                    near.append((row[0], distance))

            near.sort(key=lambda item: item[1])

            near_ids = [item[0] for item in near]

            if near_ids:
                groups.append(RelatedPhotoGroup(name="Near", photo_ids=near_ids))

        return PhotoDetail.from_photo(photo, groups=groups)

    detail = await DatabaseService.execute(_get)
    detail.location_estimate = await LocationService.get_estimate(photo_id)

    return detail


@router.post("/{photo_id}/reprocess", response_model=PhotoDetail)
async def reprocess_photo(photo_id: int, payload: ReprocessRequest) -> PhotoDetail:
    """Regenerate the alternatives of a photo from its original."""
    overrides = _build_reprocess_overrides(payload)

    try:
        await ProcessingService.reprocess(
            photo_id,
            alternatives=payload.alternatives,
            main_target=payload.main,
            overrides=overrides,
            rescan=payload.rescan,
        )
    except ReprocessError as error:
        raise HTTPException(error.status_code, str(error)) from error

    return await get_photo(photo_id)


@router.get("/{photo_id}/image")
async def get_image(photo_id: int, size: int | None = Query(None)):
    async def _get(session):
        photo = (await session.execute(select(Photo).where(Photo.id == photo_id))).scalar_one_or_none()

        if photo is None:
            raise HTTPException(404, f"Photo {photo_id} not found")

        return photo

    photo = await DatabaseService.execute(_get)

    file = photo.alternative(size) if size is not None else photo.main()

    if file is None:
        file = photo.main()

    source = PhotoService.resolve(photo, file)
    media_type, _ = mimetypes.guess_type(source.name)

    if not media_type or media_type == "application/octet-stream":
        media_type = Image.MIME.get(source.suffix.lstrip(".").upper(), media_type)

    return FileResponse(source, media_type=media_type)


PREVIEW_MAX_SIZE = 2048


@router.get("/{photo_id}/preview")
async def get_preview(photo_id: int, size: int = Query(PREVIEW_MAX_SIZE, ge=64, le=8192)):
    """Serve an EXIF-transposed, downscaled copy of the original for the processing preview.

    The editor needs the pixels *before* the tilt/crop/rescale chain, oriented the
    same way the pipeline orients them, so the normalised horizon geometry stored
    on the photo lines up. Re-encoding to WebP (bounded on the longest edge) keeps
    the response small and removes the EXIF orientation, so the browser's own
    decoding cannot disagree with the backend. The original pixel size is returned
    in headers for the size captions.
    """

    async def _get(session):
        photo = (await session.execute(select(Photo).where(Photo.id == photo_id))).scalar_one_or_none()

        if photo is None:
            raise HTTPException(404, f"Photo {photo_id} not found")

        return photo

    photo = await DatabaseService.execute(_get)
    source = PhotoService.resolve(photo, photo.original)

    def _render() -> tuple[bytes, tuple[int, int]]:
        with Image.open(source) as handle:
            image = ImageOps.exif_transpose(handle)
            image.load()
            original = image.size

            if max(image.size) > size:
                image.thumbnail((size, size), Image.Resampling.LANCZOS)

            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGB")

            buffer = BytesIO()
            image.save(buffer, format="WEBP", quality=90)

            return buffer.getvalue(), original

    data, (width, height) = await ThreadPoolService.run(_render)

    return Response(
        content=data,
        media_type="image/webp",
        headers={"X-Original-Width": str(width), "X-Original-Height": str(height)},
    )


@router.get("/{photo_id}/thumbnail")
async def get_thumbnail(photo_id: int, size: int | None = Query(None), v: str | None = Query(None)):
    """Serve a thumbnail. `v` is an optional cache-busting value and is ignored."""

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
    path = await FolderService.upload(file.filename or "photo", file)

    return {"filename": path.name, "path": FolderService.canonical(path), "alternatives": []}
