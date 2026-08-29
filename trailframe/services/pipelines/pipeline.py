import asyncio
from datetime import datetime, timedelta
from typing import Any

from trailframe.services.core.configuration_service import Node
from trailframe.services.pipelines.item import Item
from trailframe.services.scanners.scanner import ForceFlag
from trailframe.services.service import Service


class PipelineEmpty:
    pass


def is_pipeline_empty(item: Any) -> bool:
    return isinstance(item, PipelineEmpty) or item is PipelineEmpty


class Pipeline(Service):
    _queue: asyncio.Queue | None = None
    _task: asyncio.Task | None = None
    _running = False
    _success = 0
    _failure = 0
    _inflight = 0
    _reset_timestamp: datetime | None = None

    @classmethod
    def _configure(cls, config: Node) -> None:
        for scanner in cls._scanners:
            scanner.configure(config)

    @classmethod
    async def _start(cls) -> None:
        cls._running = True
        cls._queue = asyncio.Queue()
        cls._success = 0
        cls._failure = 0
        cls._reset_timestamp = None
        cls._task = asyncio.create_task(cls._process())

    @classmethod
    async def _stop(cls) -> None:
        cls._running = False

        if cls._task is not None:
            cls._task.cancel()
            cls._task = None

    @classmethod
    async def add(cls, item: Any) -> None:
        if is_pipeline_empty(item):
            cls._previous_pipeline_empty()
            return

        await cls._add(item)

    @classmethod
    def _previous_pipeline_empty(cls) -> None:
        pass

    @classmethod
    async def _add(cls, item: Any) -> None:
        if cls._queue is None:
            cls._queue = asyncio.Queue()

        await cls._queue.put(item)

    @classmethod
    def get_queue_size(cls) -> int:
        if cls._queue is None:
            return 0

        return cls._queue.qsize()

    @classmethod
    def accepts(cls, item: Any) -> bool:
        return is_pipeline_empty(item)

    @classmethod
    def get_status_message(cls) -> str:
        queue = cls.get_queue_size()

        if cls._reset_timestamp is not None and (queue > 0 or datetime.now() >= cls._reset_timestamp):
            cls._success = 0
            cls._failure = 0
            cls._reset_timestamp = None

        if cls._success == 0 and cls._failure == 0:
            return "Idle"

        total = cls._success + cls._failure + queue

        return f"({cls._success}/{cls._failure}/{total})"

    @classmethod
    async def _process(cls) -> None:
        while cls._running:
            item = await cls._queue.get()
            cls._inflight += 1

            try:
                if await cls._process_item(item):
                    cls._success += 1

                    from trailframe.services.pipelines.pipeline_service import PipelineService

                    await PipelineService.next(item, cls)
                else:
                    cls._failure += 1
            except Exception:  # noqa: BLE001
                cls._failure += 1
            finally:
                cls._queue.task_done()
                cls._inflight -= 1

            if not cls.get_queue_size() and cls._inflight == 0:
                cls._reset_timestamp = datetime.now() + timedelta(minutes=5)

                await cls._flush_stats()

                from trailframe.services.pipelines.pipeline_service import PipelineService

                await PipelineService.next(PipelineEmpty, cls)

    @classmethod
    async def _process_item(cls, item: Any) -> bool:
        if not isinstance(item, (Item, ForceFlag)):
            item = Item(item)

        return await cls._run_scanners(item)

    @classmethod
    async def _run_scanners(cls, item: Any) -> bool:
        for scanner in cls._scanners:
            await scanner.execute(item)

        return True

    @classmethod
    async def _flush_stats(cls) -> None:
        stats = []

        for scanner in cls._scanners:
            scan_stats = scanner.get_run_stats()

            if scan_stats is not None:
                stats.append(scan_stats)

        for scanner in cls._scanners:
            scanner.reset_run_stats()

        if not stats:
            return

        from trailframe.services.core.statistics_service import StatisticsService

        await StatisticsService.record_run(stats)
