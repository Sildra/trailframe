from pathlib import Path

from fastapi import APIRouter, HTTPException

from trailframe.services.configuration_service import ConfigurationService

router = APIRouter(prefix="/api/models", tags=["models"])

YOLO_MODELS = {
    "yolo26n.pt": "Nano",
    "yolo26s.pt": "Small",
    "yolo26m.pt": "Medium",
    "yolo26l.pt": "Large",
    "yolo26x.pt": "Extra Large",
}


def _models_folder() -> Path:
    return Path(ConfigurationService.root().get_path_value("general.models_folder", default_value="models"))


@router.get("")
async def list_models() -> list[str]:
    folder = _models_folder()

    if not folder.exists():
        return []

    return [f.name for f in folder.iterdir() if f.suffix == ".pt"]


@router.post("/{name}/download")
async def download_model(name: str) -> str:
    if name not in YOLO_MODELS:
        raise HTTPException(status_code=400, detail=f"Unknown model: {name}")

    folder = _models_folder()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name

    if target.exists():
        return str(target)

    from ultralytics.utils import checks

    url = f"https://github.com/ultralytics/assets/releases/download/v8.4.0/{name}"
    checks.check_file(url, download_dir=str(folder))

    if not target.exists():
        raise HTTPException(status_code=500, detail=f"Download failed for {name}")

    return str(target)
