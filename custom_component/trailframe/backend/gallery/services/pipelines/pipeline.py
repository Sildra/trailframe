import asyncio
from abc import abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from gallery.services.pipelines.executor import create_executor
from gallery.services.service import Service


class PipelineEmpty:
    pass


def is_pipeline_empty(item: Any) -> bool:
    return isinstance(item, PipelineEmpty) or item is PipelineEmpty


@dataclass
class ForcedScan:
    scanners: list[str] = field(default_factory=list)


class Pipeline(Service):
    _queue: asyncio.Queue | None = None
    _tasks: list[asyncio.Task] | None = None
    _executor: ThreadPoolExecutor | None = None
    _worker_count = 4
    _running = False
    _success = 0
    _failure = 0
    _inflight = 0
    _reset_timestamp: datetime | None = None

    @classmethod
    async def _start(cls) -> None:
        cls._running = True
        cls._queue = asyncio.Queue()
        cls._success = 0
        cls._failure = 0
        cls._reset_timestamp = None
        cls.get_executor()
        cls._tasks = [asyncio.create_task(cls._process()) for _ in range(cls._worker_count)]

    @classmethod
    async def _stop(cls) -> None:
        cls._running = False

        if cls._tasks:
            for task in cls._tasks:
                task.cancel()
            cls._tasks = None

        if cls._executor is not None:
            cls._executor.shutdown(wait=False, cancel_futures=True)
            cls._executor = None

    @classmethod
    def get_executor(cls) -> ThreadPoolExecutor:
        if cls._executor is None:
            cls._executor = create_executor(cls.get_name(), cls._worker_count)

        return cls._executor

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

        if queue > 0:
            if cls._reset_timestamp is not None:
                cls._success = 0
                cls._failure = 0
                cls._reset_timestamp = None

            total = cls._success + cls._failure + queue

            return f"({cls._success}/{cls._failure}/{total})"

        if cls._reset_timestamp and datetime.now() >= cls._reset_timestamp:
            cls._success = 0
            cls._failure = 0
            cls._reset_timestamp = None

        if cls._success == 0 and cls._failure == 0:
            return "Idle"

        total = cls._success + cls._failure

        return f"({cls._success}/{cls._failure}/{total})"

    @classmethod
    async def _process(cls) -> None:
        while cls._running:
            item = await cls._queue.get()
            cls._inflight += 1

            try:
                if await cls._process_item(item):
                    cls._success += 1

                    from gallery.services.pipeline_service import PipelineService

                    await PipelineService.next(item, cls)
                else:
                    cls._failure += 1
            except Exception:
                cls._failure += 1
            finally:
                cls._queue.task_done()
                cls._inflight -= 1

            if not cls.get_queue_size() and cls._inflight == 0:
                cls._reset_timestamp = datetime.now() + timedelta(minutes=5)

                await cls._flush_stats()

                from gallery.services.pipeline_service import PipelineService

                await PipelineService.next(PipelineEmpty, cls)

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

        from gallery.services.scanner_stats_service import ScannerStatsService

        await ScannerStatsService.record_run(stats)

    @classmethod
    @abstractmethod
    async def _process_item(cls, item: Any) -> bool:
        return True
