from fastapi import APIRouter
from pydantic import BaseModel

from trailframe.services.pipelines.basic_pipeline import BasicPipeline
from trailframe.services.pipelines.creation_pipeline import CreationPipeline
from trailframe.services.pipelines.pipeline_service import PipelineService

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


class ForcedScanRequest(BaseModel):
    scanners: list[str]


def _known_scanners() -> list[str]:
    return [scanner.name for pipeline in (CreationPipeline, BasicPipeline) for scanner in pipeline._scanners]


@router.get("/scanners")
async def list_scanners() -> list[str]:
    return _known_scanners()


@router.post("/scan")
async def trigger_scan(request: ForcedScanRequest) -> dict[str, str]:
    valid = set(_known_scanners())
    unknown = set(request.scanners) - valid

    if unknown:
        return {"status": f"unknown scanners: {', '.join(sorted(unknown))}"}

    await PipelineService.forced_scan(request.scanners)
    return {"status": "ok"}
