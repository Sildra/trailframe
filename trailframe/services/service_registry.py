from typing import ClassVar

from trailframe.services.activities.activity_service import ActivityService
from trailframe.services.activities.garmin_connect_service import GarminConnectService
from trailframe.services.activities.gpx_service import GpxService
from trailframe.services.core.configuration_service import Node
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.core.statistics_service import StatisticsService
from trailframe.services.core.thread_pool_service import ThreadPoolService
from trailframe.services.map.location_service import LocationService
from trailframe.services.map.map_service import MapService
from trailframe.services.map.tile_service import TileService
from trailframe.services.photos.duplicates_service import DuplicatesService
from trailframe.services.photos.folder_service import FolderService
from trailframe.services.photos.photo_service import PhotoService
from trailframe.services.photos.thumbnail_service import ThumbnailService
from trailframe.services.pipelines.pipeline_service import PipelineService
from trailframe.services.service import Service


class ServiceRegistry(Service):
    """Configures, starts and stops the application services.

    The service list is declared directly in the class: `configure` and `_start`
    run the services in registration order, `_stop` runs them in reverse order so
    a service that depends on another is torn down before its dependency.
    """

    _services: ClassVar[list[type[Service]]] = [
        ThreadPoolService,
        DatabaseService,
        PhotoService,
        PipelineService,
        FolderService,
        ThumbnailService,
        MapService,
        GarminConnectService,
        GpxService,
        ActivityService,
        LocationService,
        TileService,
        StatisticsService,
        DuplicatesService,
    ]

    @classmethod
    def register(cls, service: type[Service]) -> None:
        cls._services.append(service)

    @classmethod
    def _configure(cls, config: Node) -> None:
        for service in cls._services:
            service.configure(config)

    @classmethod
    async def _start(cls) -> None:
        for service in cls._services:
            await service.start()

    @classmethod
    async def _stop(cls) -> None:
        for service in reversed(cls._services):
            await service.stop()

    @classmethod
    def get_services(cls) -> list[type[Service]]:
        return list(cls._services)
