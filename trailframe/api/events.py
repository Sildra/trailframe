import asyncio
import json
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from trailframe.services.map.location_service import LocationService
from trailframe.services.pipelines.pipeline_service import PipelineService

router = APIRouter(prefix="/api/events", tags=["events"])

_server = None


def _format_sse(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data)
    return f"event: {event}\ndata: {payload}\n\n"


def _snapshot_message(was_downloading: bool) -> tuple[dict[str, Any], bool]:
    """Compose one snapshot: pipeline statuses plus a Boundaries pseudo-category
    while a boundary download is in flight. An empty string tells the frontend
    to drop the category; afterwards the key is omitted entirely."""
    message: dict[str, Any] = PipelineService.get_snapshot()
    progress = LocationService.get_download_progress()

    if progress is not None:
        message["Boundaries"] = f"({progress['current']}/{progress['failed']}/{progress['total']})"
        return message, True

    if was_downloading:
        message["Boundaries"] = ""

    return message, False


async def _event_stream():
    last_message: dict[str, Any] | None = None
    was_downloading = False

    while not _server.should_exit:
        message, was_downloading = _snapshot_message(was_downloading)

        if message != last_message:
            yield _format_sse("pipeline", message)
            last_message = message

        await asyncio.sleep(0.2)
    yield _format_sse("pipeline", {"Text": "Server is shutting down"})


@router.get("")
async def stream_events() -> StreamingResponse:
    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
