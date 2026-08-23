import argparse
from importlib import resources
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.concurrency import asynccontextmanager

from trailframe.api.about import router as about_router
from trailframe.api.activities import router as activities_router
from trailframe.api.configuration import router as configuration_router
from trailframe.api.events import router as events_router
from trailframe.api.map_data import router as map_data_router
from trailframe.api.models import router as models_router
from trailframe.api.photos import router as photos_router
from trailframe.api.pipeline import router as pipeline_router
from trailframe.api.statistics import router as statistics_router
from trailframe.api.tiles import router as tiles_router
from trailframe.services.activity_service import ActivityService
from trailframe.services.configuration_service import ConfigurationService
from trailframe.services.database_service import DatabaseService
from trailframe.services.folder_service import FolderService
from trailframe.services.garmin_connect_service import GarminConnectService
from trailframe.services.gpx_service import GpxService
from trailframe.services.location_service import LocationService
from trailframe.services.map_service import MapService
from trailframe.services.pipeline_service import PipelineService
from trailframe.services.statistics_service import StatisticsService
from trailframe.services.thumbnail_service import ThumbnailService
from trailframe.services.tile_service import TileService


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Photo Gallery API")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"), help="Configuration file")
    parser.add_argument("--folder", type=Path, default=None, help="Base folder where photos and thumbnails are stored")
    parser.add_argument("--database", type=Path, default=None, help="SQLite database")
    parser.add_argument("--port", type=int, default=None, help="API port")
    parser.add_argument("--openapi", type=Path, default=None, metavar="FILE", help="Write OpenAPI schema to FILE and exit")
    return parser.parse_args()


def create_app(args: argparse.Namespace) -> FastAPI:
    ConfigurationService.configure(args.config)
    ConfigurationService.load()
    root_node = ConfigurationService.root()
    general_node = root_node.get_node("general", "General parameters")
    api_port_node = general_node.get_node("api_port", "The API port")
    api_port_node.set_default_value(8000)
    database_node = general_node.get_node("database")
    if args.folder:
        general_node.get_node("photos_folder").set_value(str(args.folder / "photos"))
        general_node.get_node("thumbnails_folder").set_value(str(args.folder / "thumbnails"))
        general_node.get_node("activities_folder").set_value(str(args.folder / "activities"))
        general_node.get_node("maps_folder").set_value(str(args.folder / "maps"))
        general_node.get_node("models_folder").set_value(str(args.folder / "models"))
        general_node.get_node("tiles_folder").set_value(str(args.folder / "tiles"))
    if args.port:
        api_port_node.set_value(args.port)
    if args.database:
        database_node.set_value(str(args.database))

    @asynccontextmanager
    async def lifespan(app: FastAPI):

        FolderService.configure(general_node)
        PipelineService.configure(root_node)
        ThumbnailService.configure(general_node)
        DatabaseService.configure(general_node)
        GarminConnectService.configure(general_node)
        GpxService.configure(general_node)
        ActivityService.configure(general_node)
        LocationService.configure(general_node)
        MapService.configure(general_node)
        TileService.configure(root_node)
        StatisticsService.configure(general_node)
        ConfigurationService.save()

        # Tables must exist before the pipelines consume items
        await DatabaseService.start()
        await PipelineService.start()
        await FolderService.start()
        # signal.signal(signal.SIGINT, stop_streams)

        yield

        await FolderService.stop()
        await PipelineService.stop()
        await DatabaseService.stop()

    app = FastAPI(title="Trailframe", version="0.1.0", lifespan=lifespan)

    app.include_router(about_router)
    app.include_router(photos_router)
    app.include_router(models_router)
    app.include_router(pipeline_router)
    app.include_router(map_data_router)
    app.include_router(configuration_router)
    app.include_router(activities_router)
    app.include_router(events_router)
    app.include_router(statistics_router)
    app.include_router(tiles_router)

    dev_dist = Path("frontend/dist")
    pkg_dist = Path(str(resources.files("trailframe") / "frontend" / "dist"))
    frontend_dir = dev_dist if dev_dist.is_dir() else pkg_dist

    app.frontend("/", directory=frontend_dir)

    return app


def main() -> None:
    args = parse_arguments()
    app = create_app(args)

    if args.openapi:
        import json

        args.openapi.write_text(json.dumps(app.openapi(), indent=2))
        return

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=ConfigurationService.root().get_path_value("general.api_port"),
        timeout_graceful_shutdown=5
    )


if __name__ == "__main__":
    main()
