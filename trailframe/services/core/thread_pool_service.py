from concurrent.futures import ThreadPoolExecutor
from typing import ClassVar

from trailframe.services.core.configuration_service import Node
from trailframe.services.service import Service


class ThreadPoolService(Service):
    """Single shared thread pool used for all heavy/blocking workloads.

    Replaces the per-domain executors (one per pipeline, one for map rendering,
    one for Garmin calls, etc.) with a single bounded pool. This caps total
    concurrency — critical on memory-constrained devices (e.g. an RPi) where
    running several heavy scans (like YOLO object detection) in parallel crashes
    the process.
    """

    _pool: ClassVar[ThreadPoolExecutor | None] = None
    _max_workers: ClassVar[int] = 2

    @classmethod
    def _configure(cls, config: Node) -> None:
        cls._max_workers = int(
            config.get_path_value("general.thread_pool_size", "Number of threads in the shared worker pool", 2)
        )

    @classmethod
    async def _start(cls) -> None:
        size = max(1, cls._max_workers)
        cls._pool = ThreadPoolExecutor(max_workers=size, thread_name_prefix="common")
        cls._log(f"started common pool with {size} worker(s)")

    @classmethod
    async def _stop(cls) -> None:
        if cls._pool is not None:
            cls._pool.shutdown(wait=False, cancel_futures=True)
            cls._pool = None

    @classmethod
    def get_executor(cls) -> ThreadPoolExecutor:
        if cls._pool is None:
            cls._pool = ThreadPoolExecutor(max_workers=max(1, cls._max_workers), thread_name_prefix="common")

        return cls._pool
