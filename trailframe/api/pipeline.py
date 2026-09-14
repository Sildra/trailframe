import asyncio
import io

from fastapi import APIRouter, File, Form, UploadFile
from PIL import Image
from pydantic import BaseModel

from trailframe.models.photo import Photo
from trailframe.services.core.configuration_service import ConfigurationService
from trailframe.services.core.thread_pool_service import ThreadPoolService
from trailframe.services.pipelines.item import Item
from trailframe.services.pipelines.pipeline_service import PipelineService
from trailframe.services.scanners import create_scanner, get_scanner_definitions, remote_enabled
from trailframe.services.scanners.scanner import ForceFlag

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

_scanner_cache: dict = {}
"""Cached scanner instances so heavy resources (e.g. the loaded YOLO model in
ObjectScanner) are created once per remote server instead of per request."""


class ForcedScanRequest(BaseModel):
    scanners: list[str]


def _known_scanners() -> list[str]:
    return [definition["name"] for definition in get_scanner_definitions() if definition["can_be_disabled"]]


def _get_scanner_by_name(name: str):
    if not remote_enabled(name):
        return None

    scanner = _scanner_cache.get(name)

    if scanner is None:
        scanner = create_scanner(name)

        if scanner is None:
            return None

        _scanner_cache[name] = scanner

    scanner.configure(ConfigurationService.root())
    return scanner


def _execute_remote_scanners(item: Item, scanner_instances: list, forced_names: list[str] | None = None) -> None:
    """Run the delegated scanners off the event loop, on the shared thread pool.

    `scanner.execute` is async, so each pool invocation drives a short-lived
    event loop; heavy resources (e.g. the YOLO model) stay cached on the
    scanner instances shared between requests. A `ForceFlag` is fed to the
    instances before running so named scanners bypass their `accept_` gating,
    and cleared afterwards so later requests scan normally.
    """
    forced = forced_names or []
    loop = asyncio.new_event_loop()

    async def _scan():
        if forced:
            for scanner in scanner_instances:
                scanner.accept(ForceFlag(forced))

        try:
            for scanner in scanner_instances:
                await scanner.execute(item)
        finally:
            if forced:
                for scanner in scanner_instances:
                    scanner.accept(ForceFlag([]))

    try:
        loop.run_until_complete(_scan())
    finally:
        loop.close()


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
async def remote_scan(file: UploadFile = File(...), scanners: str = Form(""), forced: str = Form("")) -> dict:
    scanner_names = [s.strip() for s in scanners.split(",") if s.strip()]
    forced_names = [s.strip() for s in forced.split(",") if s.strip()]
    content = await file.read()

    try:
        image = Image.open(io.BytesIO(content))
    except (OSError, ValueError):
        image = None

    photo = Photo(path=file.filename or "photo", filename=file.filename, file_size=len(content), source="Remote")
    item = Item(photo, image=image)
    scanner_instances = [scanner for name in scanner_names if (scanner := _get_scanner_by_name(name)) is not None]

    await ThreadPoolService.run(_execute_remote_scanners, item, scanner_instances, forced_names)

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
