import logging
import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from trailframe.log import get_logger
from trailframe.models.photo import Photo
from trailframe.services.core.configuration_service import Node
from trailframe.services.pipelines.item import Item


class ScannerResult(Enum):
    SUCCESS = "success"
    ERROR = "error"


class ForceFlag:
    def __init__(self, scanners: list[str] | None = None):
        self.scanners: list[str] = scanners or []


class Scanner(ABC):
    def __init__(self, name: str):
        self.name = name
        self._can_be_disabled = True
        self._can_be_remote = False
        self._enabled = True
        self._forced = False
        self._run_count = 0
        self._run_total_ms = 0.0

    @staticmethod
    def _log(message: str, level: int = logging.INFO) -> None:
        get_logger().log(level, message)

    def configure(self, config: Node) -> None:
        if self._can_be_disabled:
            self._enabled = config.get_path_value(f"scanners.{self.name}.enabled", f"Enable {self.name} scanner", True)
        if self._can_be_remote:
            pass
        self.configure_(config)


    def configure_(self, config: Node) -> None:
        pass

    def accept(self, item: Any) -> bool:
        if self._can_be_disabled:
            if isinstance(item, ForceFlag):
                self._forced = self.name in item.scanners
                return False

            if not self._enabled:
                return False

            if self._forced:
                return True

        if isinstance(item, Photo):
            return self.accept_(item)
        if isinstance(item, Item):
            return self.accept_(item.photo)

        return False

    def accept_(self, item: Photo) -> bool:
        return True

    async def execute(self, item: Any) -> ScannerResult:
        if not self.accept(item):
            return ScannerResult.SUCCESS

        if not isinstance(item, Item):
            return ScannerResult.SUCCESS

        start = time.perf_counter()

        try:
            changed = await self.executePhoto(item)
        except Exception as exception:  # noqa: BLE001
            self._log(f"Scanner '{self.name}' failed on {item.photo.path}: {exception}", logging.ERROR)

            return ScannerResult.ERROR

        self._record((time.perf_counter() - start) * 1000)

        if changed:
            item.updated = True

        return ScannerResult.SUCCESS

    def get_run_stats(self) -> dict | None:
        if self._run_count == 0:
            return None

        return {"scanner": self.name, "count": self._run_count, "total_ms": self._run_total_ms}

    def reset_run_stats(self) -> None:
        self._run_count = 0
        self._run_total_ms = 0.0

    def _record(self, elapsed_ms: float) -> None:
        self._run_count += 1
        self._run_total_ms += elapsed_ms

    def add_scanner(self, photo: Photo) -> None:
        tracked = list(photo.scanners or [])

        if self.name not in tracked:
            tracked.append(self.name)
            photo.scanners = tracked

    @abstractmethod
    async def executePhoto(self, item: Item) -> bool:
        pass
