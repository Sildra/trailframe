import re
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from trailframe.models.activity import Activity, ActivitySummary, GarminActivitySummary, GpxActivitySummary
from trailframe.models.photo import Photo, PhotoDetail
from trailframe.services.activities.activity_service import ActivityService
from trailframe.services.activities.garmin_connect_service import GarminConnectService
from trailframe.services.activities.gpx_service import GpxService
from trailframe.services.map.map_service import MapService
from trailframe.services.photos.photo_service import PhotoService

router = APIRouter(prefix="/api/activities", tags=["activities"])


class ImportResult(BaseModel):
    success: bool


@router.get("", response_model=list[ActivitySummary])
async def list_activities() -> list[ActivitySummary]:
    return await ActivityService.list_activities()


@router.get("/garmin", response_model=list[GarminActivitySummary])
async def list_garmin_activities() -> list[GarminActivitySummary]:
    return await GarminConnectService.list_summaries()


@router.post("/garmin/sync", response_model=ImportResult)
async def garmin_sync(credentials: dict[str, Any]) -> ImportResult:
    success = await ActivityService.sync_garmin(credentials.get("email", ""), credentials.get("password", ""))

    if not success:
        raise HTTPException(status_code=401, detail="Garmin login failed")

    return ImportResult(success=True)


@router.get("/gpx", response_model=list[GpxActivitySummary])
async def list_gpx_activities() -> list[GpxActivitySummary]:
    return await GpxService.list_summaries()


@router.post("/gpx/upload", response_model=GpxActivitySummary)
async def upload_gpx(file: UploadFile = File(...)) -> GpxActivitySummary:
    content = (await file.read()).decode("utf-8", errors="replace")

    gpx_activity = await GpxService.save(content, file.filename or "activity.gpx")

    if gpx_activity is None:
        raise HTTPException(status_code=400, detail="Invalid GPX file")

    return GpxActivitySummary(
        id=gpx_activity.id,
        filename=gpx_activity.filename,
        name=gpx_activity.name,
        activity_type=gpx_activity.activity_type,
        start_time=gpx_activity.start_time,
        distance=gpx_activity.distance,
        duration=gpx_activity.duration,
    )


@router.post("/gpx/import/{gpx_id}", response_model=Activity)
async def import_gpx(gpx_id: int) -> Activity:
    activity = await ActivityService.import_gpx(gpx_id)

    if activity is None:
        raise HTTPException(status_code=404, detail="GPX activity not found")

    return activity


@router.post("/import/{activity_id}", response_model=Activity)
async def import_activity(activity_id: int) -> Activity:
    activity = await ActivityService.import_activity(activity_id)

    if activity is None:
        raise HTTPException(status_code=404, detail="Garmin activity not found")

    return activity


@router.get("/{activity_id}/map")
async def activity_map(activity_id: int) -> FileResponse:
    activity = await ActivityService.get_activity(activity_id)

    if activity is None or not activity.activity_id:
        raise HTTPException(status_code=404, detail="Activity not found")

    path = MapService.get_map(activity.activity_id)

    if not path.exists():
        raise HTTPException(status_code=404, detail="Map not found")

    return FileResponse(path, media_type="image/svg+xml")


@router.get("/{activity_id}/traces")
async def activity_traces(activity_id: int) -> FileResponse:
    activity = await ActivityService.get_activity(activity_id)

    if activity is None or not activity.activity_id:
        raise HTTPException(status_code=404, detail="Activity not found")

    path = MapService.get_trace(activity.activity_id)

    if not path.exists():
        raise HTTPException(status_code=404, detail="Trace not found")

    return FileResponse(path, media_type="image/svg+xml")


@router.get("/{activity_id}/photos", response_model=list[PhotoDetail])
async def activity_photos(activity_id: int) -> list[PhotoDetail]:
    photos = await ActivityService.list_activity_photos(activity_id)

    return [PhotoDetail.from_photo(photo) for photo in photos]


def _build_zip_response(activity: Activity, photos: list[Photo], overlay_path: Path | None = None) -> Response:
    buffer = BytesIO()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for photo in photos:
            path = PhotoService.resolve(photo)

            if path.is_file():
                archive.write(path, arcname=path.name)

        if overlay_path is not None and overlay_path.is_file():
            archive.write(overlay_path, arcname="map.png")

    base = re.sub(r"[^A-Za-z0-9._-]+", "_", activity.name or f"activity-{activity.id}").strip("_")
    filename = f"{base}.zip" if base else f"activity-{activity.id}.zip"

    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{activity_id}/zip")
async def activity_zip(activity_id: int) -> Response:
    activity = await ActivityService.get_activity(activity_id)

    if activity is None:
        raise HTTPException(status_code=404, detail="Activity not found")

    photos = await ActivityService.list_activity_photos(activity_id)

    return _build_zip_response(activity, photos)


@router.post("/{activity_id}/zip")
async def activity_zip_with_overlay(activity_id: int, overlay: Annotated[UploadFile | None, File()] = None) -> Response:
    activity = await ActivityService.get_activity(activity_id)

    if activity is None:
        raise HTTPException(status_code=404, detail="Activity not found")

    photos = await ActivityService.list_activity_photos(activity_id)

    overlay_path = None

    if overlay is not None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as file:
            file.write(await overlay.read())
            overlay_path = Path(file.name)

    try:
        return _build_zip_response(activity, photos, overlay_path)
    finally:
        if overlay_path is not None:
            overlay_path.unlink(missing_ok=True)


@router.get("/{activity_id}", response_model=Activity)
async def get_activity(activity_id: int) -> Activity:
    activity = await ActivityService.get_activity(activity_id)

    if activity is None:
        raise HTTPException(status_code=404, detail="Activity not found")

    return activity


@router.delete("/{activity_id}")
async def delete_activity(activity_id: int) -> None:
    deleted = await ActivityService.delete_activity(activity_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Activity not found")
