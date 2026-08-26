import asyncio
import json
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from trailframe.services.pipeline_service import PipelineService

router = APIRouter(prefix="/api/events", tags=["events"])

_server = None


def _format_sse(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data)
    return f"event: {event}\ndata: {payload}\n\n"


async def _event_stream():
    last_message: dict[str, Any] | None = None

    while not _server.should_exit:
        message = PipelineService.get_snapshot()

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
