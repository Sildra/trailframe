import asyncio
import queue
import threading
from datetime import datetime, timedelta
from typing import Any

from trailframe.models.photo import Photo
from trailframe.services.core.configuration_service import Node
from trailframe.services.pipelines.item import Item
from trailframe.services.scanners.scanner import ForceFlag, Scanner, ScannerResult


class PipelineEmpty:
    pass


_STOP = object()


class Pipeline:
    def __init__(self, name: str, scanners: list[Scanner]):
        super().__init__()
        self._name = name
        self._queue: queue.Queue | None = None
        self._thread: threading.Thread | None = None
        self._scanners: list[Scanner] = scanners
        self._success = 0
        self._failure = 0
        self._reset_timestamp: datetime | None = None
    

    def configure(self, config: Node) -> None:
        for scanner in self._scanners:
            scanner.configure(config)

    async def start(self) -> None:
        self._queue = queue.Queue()
        self._success = 0
        self._failure = 0
        self._reset_timestamp = None
        self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
        self._thread.start()

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._process())
        finally:
            loop.close()

    async def stop(self) -> None:
        self._queue.put(_STOP)

        self._thread.join(timeout=5)
        self._thread = None


    async def add(self, item: Any) -> None:
        self._queue.put(item)

    def _previous_pipeline_empty(self) -> None:
        pass
        
    def get_queue_size(self) -> int:
        return self._queue.qsize()

    def accepts(self, item: Any) -> bool:
        if isinstance(item, (ForceFlag, PipelineEmpty)):
            return True

        return any(scanner.accept(item) for scanner in self._scanners)

    def get_status_message(self) -> str:
        queue = self.get_queue_size()

        if self._reset_timestamp is not None and queue == 0 and datetime.now() >= self._reset_timestamp:
            self._success = 0
            self._failure = 0
            self._reset_timestamp = None

        if queue == 0 and self._success == 0 and self._failure == 0:
            return "Idle"

        total = self._success + self._failure + queue

        return f"({self._success}/{self._failure}/{total})"

    async def _process(self) -> None:
        while True:
            item = self._queue.get()
            self._reset_timestamp = datetime.now() + timedelta(minutes=5)

            if item is _STOP:
                break

            try:
                if await self._process_item(item):
                    self._success += 1

                    from trailframe.services.pipelines.pipeline_service import PipelineService

                    await PipelineService.next(item, self)
                else:
                    self._failure += 1
            except Exception:  # noqa: BLE001
                self._failure += 1
            finally:
                self._queue.task_done()

            if not self.get_queue_size():
                self._flush_stats()

                from trailframe.services.pipelines.pipeline_service import PipelineService

                #await PipelineService.next(PipelineEmpty, self)

    async def _process_item(self, item: Any) -> bool:
        if isinstance(item, Photo):
            item = Item(item)

        success = await self._run_scanners(item)
        if isinstance(item, Item):
            item.image.close()

        return success
        

    async def _run_scanners(self, item: Any) -> bool:
        success: bool = True
        for scanner in self._scanners:
            scanner_result = await scanner.execute(item)
            success &= (scanner_result is ScannerResult.SUCCESS)

        return success

    def _flush_stats(self) -> None:
        stats = []

        for scanner in self._scanners:
            scan_stats = scanner.get_run_stats()

            if scan_stats is not None:
                stats.append(scan_stats)

        for scanner in self._scanners:
            scanner.reset_run_stats()

        if not stats:
            return

        from trailframe.services.core.statistics_service import StatisticsService

        StatisticsService.record_run(stats)
