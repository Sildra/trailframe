from typing import Any

from fastapi import APIRouter

from trailframe.services.core.configuration_service import ConfigurationService

router = APIRouter(prefix="/api/configuration", tags=["configuration"])


@router.get("")
async def get_configuration() -> dict[str, Any]:
    return ConfigurationService.to_json()


@router.post("")
async def update_configuration(values: dict[str, Any]) -> dict[str, Any]:
    ConfigurationService.from_json(values)
    ConfigurationService.save()
    return ConfigurationService.to_json()
