from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from trailframe.services.core.app_data import HARDWARE_DETECTION, AppData, read_value
from trailframe.services.core.configuration_service import Node
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.scanners import get_scanner_definitions
from trailframe.services.service import Service

MIN_FREE_RAM_GB = 1.0


def detect_free_memory_gb() -> float | None:
    """Return the free (available) physical memory in GB, or None when it cannot be read."""
    if sys.platform == "win32":
        return _windows_free_memory_gb()

    if sys.platform == "darwin":
        return _darwin_free_memory_gb()

    return _linux_free_memory_gb()


def _windows_free_memory_gb() -> float | None:
    try:
        import ctypes

        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(MemoryStatusEx)

        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None

        return round(status.ullAvailPhys / 1024**3, 1)
    except (AttributeError, OSError):
        return None


def _darwin_free_memory_gb() -> float | None:
    try:
        page_size = int(
            subprocess.run(
                ["sysctl", "-n", "hw.pagesize"], capture_output=True, text=True, timeout=5, check=True
            ).stdout.strip()
        )
        stats = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5, check=True).stdout
    except (OSError, subprocess.SubprocessError, ValueError):
        return None

    free_labels = ("Pages free:", "Pages inactive:", "Pages speculative:", "Pages purgeable:")
    pages = 0

    for line in stats.splitlines():
        if not line.startswith(free_labels):
            continue

        try:
            pages += int(line.split(":", 1)[1].strip().rstrip("."))
        except (IndexError, ValueError):
            continue

    return round(pages * page_size / 1024**3, 1) if pages else None


def _linux_free_memory_gb() -> float | None:
    try:
        content = Path("/proc/meminfo").read_text(encoding="utf-8")
    except OSError:
        return None

    values: dict[str, int] = {}

    for line in content.splitlines():
        name, _, rest = line.partition(":")

        if name not in ("MemAvailable", "MemFree"):
            continue

        try:
            values[name] = int(rest.split()[0])
        except (IndexError, ValueError):
            continue

    kilobytes = values.get("MemAvailable") or values.get("MemFree")

    return round(kilobytes / 1024**2, 1) if kilobytes is not None else None


def _names(value: Any) -> list[str]:
    return [str(name) for name in value] if isinstance(value, list) else []


def plan_detection(
    free_ram_gb: float | None, heavy: list[str], previous: dict[str, Any] | None
) -> tuple[dict[str, Any], list[str]]:
    """Decide the detection record and the heavy scanners to disable.

    Detection runs again only for heavy scanners that were not present the last
    time it ran, so a scanner the user re-enabled is never disabled again.
    """
    known = set(_names(previous.get("heavy"))) if previous else set()
    fresh = [name for name in heavy if name not in known]
    low_memory = free_ram_gb is not None and free_ram_gb < MIN_FREE_RAM_GB
    auto_disabled = _names(previous.get("auto_disabled")) if previous else []
    disabled = [name for name in fresh if low_memory and name not in auto_disabled]
    auto_disabled.extend(disabled)

    record = {
        "free_ram_gb": free_ram_gb,
        "min_free_ram_gb": MIN_FREE_RAM_GB,
        "low_memory": low_memory,
        "heavy": sorted(known | set(heavy)),
        "auto_disabled": sorted(auto_disabled),
        "detected_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }

    return record, disabled


class HardwareService(Service):
    """Detect the free memory and disable heavy scanners on small machines.

    Detection runs on startup and is recorded in the generic `app_data` table:
    a heavy scanner added by a later release is not in the record yet, so it is
    evaluated on the next start even though the user's earlier choices are kept.
    """

    _reconfig_safe = False
    _requires = ("DatabaseService",)

    _record: ClassVar[dict[str, Any] | None] = None

    @classmethod
    def _configure(cls, config: Node) -> None:
        cls._record = None
        free_ram_gb = detect_free_memory_gb()
        heavy = [
            definition["name"]
            for definition in get_scanner_definitions()
            if definition["heavy"] and definition["can_be_disabled"]
        ]
        record, disabled = plan_detection(free_ram_gb, heavy, cls._read_previous())
        cls._record = record

        for name in disabled:
            config.get_node(f"scanners.{name}.enabled").set_value(False)

        if disabled:
            cls._log(
                f"detected {free_ram_gb} GB of free RAM (heavy features need {MIN_FREE_RAM_GB} GB): "
                f"disabled {', '.join(disabled)} "
                "(see the 'Hardware & performance' help page)",
                logging.WARNING,
            )
        elif record["low_memory"]:
            cls._log(
                f"detected {free_ram_gb} GB of free RAM (heavy features need {MIN_FREE_RAM_GB} GB); "
                "heavy scanners were already handled on a previous start"
            )

    @classmethod
    def _read_previous(cls) -> dict[str, Any] | None:
        raw = read_value(DatabaseService.get_database_path(), HARDWARE_DETECTION)

        if not raw:
            return None

        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            return None

        return record if isinstance(record, dict) else None

    @classmethod
    async def _start(cls) -> None:
        if cls._record is None:
            return

        record = cls._record

        async def _store(session) -> None:
            await AppData.set_value(session, HARDWARE_DETECTION, json.dumps(record))
            await session.commit()

        await DatabaseService.execute(_store)
