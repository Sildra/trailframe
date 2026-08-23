from typing import Any

from sqlalchemy import select

from gallery.models.photo import Photo
from gallery.services.configuration_service import Node
from gallery.services.database_service import DatabaseService
from gallery.services.pipelines.basic_pipeline import BasicPipeline
from gallery.services.pipelines.creation_pipeline import CreationPipeline
from gallery.services.pipelines.pipeline import ForcedScan, Pipeline
from gallery.services.service import Service


class PipelineService(Service):
    _pipelines: list[type[Pipeline]] = []

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
        await cls.next(ForcedScan(scanner_names))

        async with DatabaseService.create_session() as session:
            result = await session.execute(select(Photo).order_by(Photo.id.asc()))

            for photo in result.scalars().all():
                session.expunge(photo)
                await cls.next(photo)

        await cls.next(ForcedScan())

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
