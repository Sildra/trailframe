import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel

from trailframe.models.photo import Photo
from trailframe.services.core.configuration_service import ConfigurationService
from trailframe.services.pipelines.item import Item
from trailframe.services.pipelines.pipeline_service import PipelineService
from trailframe.services.scanners import create_scanner, get_scanner_definitions

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


class ForcedScanRequest(BaseModel):
    scanners: list[str]


def _known_scanners() -> list[str]:
    return [definition["name"] for definition in get_scanner_definitions() if definition["can_be_disabled"]]


def _get_scanner_by_name(name: str):
    scanner = create_scanner(name)

    if scanner is None:
        return None

    scanner.configure(ConfigurationService.root())
    return scanner


@router.get("/scanners")
async def list_scanners() -> list[str]:
    values = _known_scanners()
    values.sort()
    return values


@router.post("/scan")
async def trigger_scan(request: ForcedScanRequest) -> dict[str, str]:
    valid = set(_known_scanners())
    unknown = set(request.scanners) - valid

    if unknown:
        return {"status": f"unknown scanners: {', '.join(sorted(unknown))}"}

    await PipelineService.forced_scan(request.scanners)
    return {"status": "ok"}


@router.post("/remote-scan")
async def remote_scan(file: UploadFile = File(...), scanners: str = Form("")) -> dict:
    scanner_names = [s.strip() for s in scanners.split(",") if s.strip()]

    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename or "photo").suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        photo = Photo(path=str(tmp_path), source="File", filename=file.filename)
        item = Item(photo)

        for name in scanner_names:
            scanner = _get_scanner_by_name(name)

            if scanner is None:
                continue

            await scanner.execute(item)

        return {
            "filename": photo.filename,
            "file_size": photo.file_size,
            "date": photo.date,
            "objects": photo.objects or [],
            "scanners": photo.scanners or [],
            "exif": photo.exif or {},
            "latitude": photo.latitude,
            "longitude": photo.longitude,
            "location_source": photo.location_source,
            "country": photo.country,
            "location": photo.location,
            "wireframe": photo.wireframe,
            "tags": photo.tags or [],
            "scores": photo.scores or {},
            "phash": photo.phash.hex() if photo.phash else None,
        }
    finally:
        tmp_path.unlink(missing_ok=True)
