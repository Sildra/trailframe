import inspect
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor

from trailframe.models.photo import Photo
from trailframe.services.configuration_service import Node
from trailframe.services.pipelines.executor import run_in_thread


class Scanner(ABC):
    def __init__(self, name: str):
        self.name = name
        self.enabled = True
        self.needs_tracking = False
        self._run_count = 0
        self._run_total_ms = 0.0

    def configure(self, config: Node) -> None:
        self.enabled = config.get_path_value(f"scanners.{self.name}.enabled", f"Enable {self.name} scanner", True)

    def accept(self, photo: Photo) -> bool:
        return True

    async def execute(self, photo: Photo, executor: ThreadPoolExecutor, *, force: bool = False) -> None:
        if not force and not self.enabled:
            return

        start = time.perf_counter()

        try:
            scan = self.scan

            if inspect.iscoroutinefunction(scan):
                await scan(photo)
            else:
                await run_in_thread(executor, scan, photo)
        except Exception as exception:
            print(f"Scanner '{self.name}' failed on {photo.path}: {exception}")
            return

        self._record((time.perf_counter() - start) * 1000)

        if self.needs_tracking:
            tracked = list(photo.scanners or [])

            if self.name not in tracked:
                tracked.append(self.name)
                photo.scanners = tracked

    def get_run_stats(self) -> dict | None:
        if self._run_count == 0:
            return None

        return {
            "scanner": self.name,
            "count": self._run_count,
            "total_ms": self._run_total_ms,
        }

    def reset_run_stats(self) -> None:
        self._run_count = 0
        self._run_total_ms = 0.0

    def _record(self, elapsed_ms: float) -> None:
        self._run_count += 1
        self._run_total_ms += elapsed_ms

    @abstractmethod
    async def scan(self, photo: Photo) -> None:
        pass
