import asyncio
import queue
import threading
from datetime import datetime, timedelta
from typing import Any, ClassVar

from trailframe.models.photo import Photo
from trailframe.services.core.configuration_service import Node
from trailframe.services.pipelines.item import Item
from trailframe.services.scanners.scanner import ForceFlag, Scanner, ScannerResult
from trailframe.services.service import Service


class PipelineEmpty:
    pass


_STOP = object()


class Pipeline(Service):
    _queue: ClassVar[queue.Queue | None] = None
    _thread: ClassVar[threading.Thread | None] = None
    _scanners: ClassVar[list[Scanner]] = []
    _success = 0
    _failure = 0
    _reset_timestamp: datetime | None = None
    

    @classmethod
    def _configure(cls, config: Node) -> None:
        for scanner in cls._scanners:
            scanner.configure(config)

    @classmethod
    async def _start(cls) -> None:
        cls._queue = queue.Queue()
        cls._success = 0
        cls._failure = 0
        cls._reset_timestamp = None
        cls._thread = threading.Thread(target=cls._run, name=cls.get_name(), daemon=True)
        cls._thread.start()

    @classmethod
    def _run(cls):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(cls._process())
        finally:
            loop.close()

    @classmethod
    async def _stop(cls) -> None:
        cls._queue.put(_STOP)

        cls._thread.join(timeout=5)
        cls._thread = None


    @classmethod
    async def add(cls, item: Any) -> None:
        cls._queue.put(item)

    @classmethod
    def _previous_pipeline_empty(cls) -> None:
        pass
        
    @classmethod
    def get_queue_size(cls) -> int:
        return cls._queue.qsize()

    @classmethod
    def accepts(cls, item: Any) -> bool:
        if isinstance(item, (ForceFlag, PipelineEmpty)):
            return True

        return any(scanner.accept(item) for scanner in cls._scanners)

    @classmethod
    def get_status_message(cls) -> str:
        queue = cls.get_queue_size()

        if cls._reset_timestamp is not None and queue == 0 and datetime.now() >= cls._reset_timestamp:
            cls._success = 0
            cls._failure = 0
            cls._reset_timestamp = None

        if queue == 0 and cls._success == 0 and cls._failure == 0:
            return "Idle"

        total = cls._success + cls._failure + queue

        return f"({cls._success}/{cls._failure}/{total})"

    @classmethod
    async def _process(cls) -> None:
        while True:
            item = cls._queue.get()
            cls._reset_timestamp = datetime.now() + timedelta(minutes=5)

            if item is _STOP:
                break

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

            if not cls.get_queue_size():
                cls._flush_stats()

                from trailframe.services.pipelines.pipeline_service import PipelineService

                #await PipelineService.next(PipelineEmpty, cls)

    @classmethod
    async def _process_item(cls, item: Any) -> bool:
        if isinstance(item, Photo):
            item = Item(item)

        return await cls._run_scanners(item)

    @classmethod
    async def _run_scanners(cls, item: Any) -> bool:
        success: bool = True
        for scanner in cls._scanners:
            scanner_result = await scanner.execute(item)
            success &= (scanner_result is ScannerResult.SUCCESS)

        return success

    @classmethod
    def _flush_stats(cls) -> None:
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

        StatisticsService.record_run(stats)
