from typing import Any, ClassVar

from sqlalchemy import select

from trailframe.models.photo import Photo
from trailframe.services.core.configuration_service import Node
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.pipelines.basic_pipeline import BasicPipeline
from trailframe.services.pipelines.creation_pipeline import CreationPipeline
from trailframe.services.pipelines.item import Item
from trailframe.services.pipelines.pipeline import Pipeline
from trailframe.services.scanners.scanner import ForceFlag
from trailframe.services.service import Service


class PipelineService(Service):
    _pipelines: ClassVar[list[type[Pipeline]]] = []

    @classmethod
    def _configure(cls, config: Node) -> None:
        cls._pipelines = [CreationPipeline, BasicPipeline]

        for pipeline in cls._pipelines:
            pipeline.configure(config)

    @classmethod
    async def _start(cls) -> None:
        for pipeline in cls._pipelines:
            await pipeline.start()

    @classmethod
    async def _stop(cls) -> None:
        for pipeline in reversed(cls._pipelines):
            await pipeline.stop()

    @classmethod
    async def next(cls, item: Any, pipeline: type[Pipeline] | None = None) -> None:
        if pipeline is None:
            candidates = cls._pipelines
        else:
            index = cls._pipelines.index(pipeline)
            candidates = cls._pipelines[index + 1 :]

        for candidate in candidates:
            if candidate.accepts(item):
                await candidate.add(item)
                return

    @classmethod
    async def forced_scan(cls, scanner_names: list[str]) -> None:
        await cls.next(ForceFlag(scanner_names))

        async def _load_photos(session) -> list[Photo]:
            result = await session.execute(select(Photo).order_by(Photo.id.asc()))
            photos = list(result.scalars().all())

            for photo in photos:
                session.expunge(photo)

            return photos

        for photo in await DatabaseService.execute(_load_photos):
            await cls.next(Item(photo))

        await cls.next(ForceFlag([]))

    @classmethod
    def get_queue_size(cls) -> int:
        return sum(pipeline.get_queue_size() for pipeline in cls._pipelines)

    @classmethod
    def get_snapshot(cls) -> dict[str, Any]:
        message: dict[str, Any] = {
            f"{pipeline.get_name().removesuffix('Pipeline')}": pipeline.get_status_message()
            for pipeline in cls._pipelines
        }

        return message
