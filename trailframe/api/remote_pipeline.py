import tempfile
from pathlib import Path

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from trailframe.models.photo import Photo
from trailframe.services.pipelines.pipeline_service import PipelineService

router = APIRouter(prefix="/api/pipeline/remote", tags=["pipeline"])


class RemotePipelineInfo(BaseModel):
    name: str
    remote: str
    scanners: list[str]


@router.get("", response_model=list[RemotePipelineInfo])
async def list_remote_pipelines() -> list[RemotePipelineInfo]:
    return [RemotePipelineInfo(**entry) for entry in PipelineService.get_remote_pipelines()]


@router.get("/{name}", response_model=RemotePipelineInfo)
async def get_remote_pipeline(name: str) -> RemotePipelineInfo:
    entry = PipelineService.get_remote_pipeline(name)

    if entry is None:
        raise HTTPException(404, f"Remote pipeline '{name}' not found")

    return RemotePipelineInfo(**entry)


@router.post("/{name}/push")
async def push_to_remote_pipeline(name: str, file: UploadFile = File(...)) -> dict[str, str]:
    entry = PipelineService.get_remote_pipeline(name)

    if entry is None:
        raise HTTPException(404, f"Remote pipeline '{name}' not found")

    pipeline = PipelineService.get_pipeline(name)

    if pipeline is None or pipeline._queue is None:
        raise HTTPException(503, f"Pipeline '{name}' is not running")

    content = await file.read()

    temp_dir = Path(tempfile.gettempdir()) / "trailframe"
    temp_dir.mkdir(exist_ok=True)

    temp_path = temp_dir / (file.filename or "photo.jpg")
    temp_path.write_bytes(content)

    photo = Photo(path=str(temp_path), filename=file.filename, file_size=len(content))
    pipeline.add(photo)

    return {"status": "queued", "scanners": ",".join(entry["scanners"])}


@router.get("/{name}/status")
async def get_remote_pipeline_status(name: str) -> dict[str, str]:
    entry = PipelineService.get_remote_pipeline(name)

    if entry is None:
        raise HTTPException(404, f"Remote pipeline '{name}' not found")

    url = f"{entry['remote'].rstrip('/')}/api/pipeline/scanners"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)

            if response.status_code != 200:
                return {"status": "error", "detail": f"Remote returned {response.status_code}"}

            return {"status": "ok", "scanners": ",".join(response.json())}
    except httpx.ConnectError:
        return {"status": "unreachable"}
    except httpx.TimeoutException:
        return {"status": "timeout"}
