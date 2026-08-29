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
from trailframe.services.activities.activity_service import ActivityService
from trailframe.services.activities.garmin_connect_service import GarminConnectService
from trailframe.services.activities.gpx_service import GpxService
from trailframe.services.core.configuration_service import ConfigurationService
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.core.statistics_service import StatisticsService
from trailframe.services.core.thread_pool_service import ThreadPoolService
from trailframe.services.map.location_service import LocationService
from trailframe.services.map.map_service import MapService
from trailframe.services.map.tile_service import TileService
from trailframe.services.photos.folder_service import FolderService
from trailframe.services.photos.photo_service import PhotoService
from trailframe.services.photos.thumbnail_service import ThumbnailService
from trailframe.services.pipelines.pipeline_service import PipelineService


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Photo Gallery API")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"), help="Configuration file")
    parser.add_argument("--folder", type=Path, default=None, help="Base folder where photos and thumbnails are stored")
    parser.add_argument("--database", type=Path, default=None, help="SQLite database")
    parser.add_argument("--port", type=int, default=None, help="API port")
    parser.add_argument("--failsafe", action="store_true", help="Start without the FolderService (no scan/watch)")
    parser.add_argument(
        "--openapi", type=Path, default=None, metavar="FILE", help="Write OpenAPI schema to FILE and exit"
    )
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
        PhotoService.configure(general_node)
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
        ThreadPoolService.configure(general_node)
        ConfigurationService.save()

        # Tables must exist before the pipelines consume items
        await ThreadPoolService.start()
        await DatabaseService.start()
        await PhotoService.start()
        await PipelineService.start()

        if not args.failsafe:
            await FolderService.start()

        yield

        await FolderService.stop()
        await PhotoService.stop()
        await PipelineService.stop()
        await ThreadPoolService.stop()
        await DatabaseService.stop()

    root_path = args.root_path.rstrip("/") or "/"

    app = FastAPI(title="Trailframe", version="0.1.0", lifespan=lifespan, root_path=root_path)

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

    from trailframe.api import events
    from trailframe.log import TimestampAccessFormatter, TimestampFormatter

    log_config = uvicorn.config.LOGGING_CONFIG
    formatters = dict(log_config["formatters"])
    formatters["default"] = {
        "()": TimestampFormatter,
        "fmt": "%(asctime)s %(levelprefix)s %(message)s",
        "use_colors": None,
    }
    formatters["access"] = {
        "()": TimestampAccessFormatter,
        "fmt": '%(asctime)s %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
        "use_colors": None,
    }
    log_config = {**log_config, "formatters": formatters}

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=ConfigurationService.root().get_path_value("general.api_port"),
        timeout_graceful_shutdown=5,
        log_config=log_config,
    )
    config.load_app()
    server = uvicorn.Server(config)
    events._server = server

    try:
        server.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
