from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from trailframe.services.tile_service import TileService

router = APIRouter(prefix="/api/tiles", tags=["tiles"])


@router.get("/{z}/{x}/{y}.png")
async def get_tile(z: int, x: int, y: int) -> FileResponse:
    path = await TileService.get_tile(z, x, y)

    if path is None:
        raise HTTPException(404, f"No tile at {z}/{x}/{y}")

    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
