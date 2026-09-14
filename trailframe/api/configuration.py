from typing import Any

from fastapi import APIRouter

from trailframe.services.core.configuration_service import ConfigurationService
from trailframe.services.pipelines.pipeline_service import PipelineService
from trailframe.services.service_registry import ServiceRegistry

router = APIRouter(prefix="/api/configuration", tags=["configuration"])


@router.get("")
async def get_configuration() -> dict[str, Any]:
    payload = ConfigurationService.to_json()
    PipelineService.add_pipelines_payload(payload)

    return payload


@router.post("")
async def update_configuration(values: dict[str, Any]) -> dict[str, Any]:
    ConfigurationService.from_json(values)
    ServiceRegistry.configure(ConfigurationService.root())
    ConfigurationService.save()

    result = ConfigurationService.to_json()
    PipelineService.add_pipelines_payload(result)
    result["applied"] = PipelineService.get_last_reconfigure()

    return result
