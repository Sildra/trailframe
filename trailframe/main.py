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
from trailframe.api.remote_pipeline import router as remote_pipeline_router
from trailframe.api.statistics import router as statistics_router
from trailframe.api.tiles import router as tiles_router
from trailframe.services.core.configuration_service import ConfigurationService
from trailframe.services.service_registry import ServiceRegistry


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
    if args.failsafe:
        general_node.get_node("failsafe").set_value(True)

    ServiceRegistry.configure(root_node)
    ConfigurationService.save()

    @asynccontextmanager
    async def lifespan(app: FastAPI):

        # Tables must exist before the pipelines consume items
        await ServiceRegistry.start()

        yield

        await ServiceRegistry.stop()

    app = FastAPI(title="Trailframe", version="0.1.0", lifespan=lifespan)

    app.include_router(about_router)
    app.include_router(photos_router)
    app.include_router(models_router)
    app.include_router(pipeline_router)
    app.include_router(remote_pipeline_router)
    app.include_router(map_data_router)
    app.include_router(configuration_router)
    app.include_router(activities_router)
    app.include_router(events_router)
    app.include_router(statistics_router)
    app.include_router(tiles_router)

    dev_dist = Path("frontend/dist")
    pkg_dist = Path(str(resources.files("trailframe") / "frontend" / "dist"))
    frontend_dir = dev_dist if dev_dist.is_dir() else pkg_dist

    if frontend_dir.is_dir():
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

    from trailframe.log import get_logger

    get_logger().info("Gallery:   http://localhost:%s", config.port)
    get_logger().info("Swagger:   http://localhost:%s/docs", config.port)

    try:
        server.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
