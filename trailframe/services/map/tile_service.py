import asyncio
import os
import time
from itertools import cycle
from pathlib import Path
from typing import ClassVar

import requests

from trailframe.services.core.configuration_service import Node
from trailframe.services.core.thread_pool_service import ThreadPoolService
from trailframe.services.service import Service

_USER_AGENT = "ha_gallery/0.1 (local personal photo gallery)"
_EVICTION_INTERVAL = 200


class TileService(Service):
    _folder: Path | None = None
    _url_template: str = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
    _subdomains: ClassVar[list[str]] = ["a", "b", "c"]
    _ttl_days: float = 30
    _cache_bytes: int = 1024 * 1024 * 1024

    _subdomain_cycle: cycle | None = None
    _pending: ClassVar[dict[str, asyncio.Future]] = {}
    _downloads_since_eviction: int = 0

    @classmethod
    def _configure(cls, config: Node) -> None:
        cls._folder = Path(
            config.get_path_value("general.tiles_folder", "Folder where cached map tiles are stored", "tiles")
        )
        cls._url_template = str(
            config.get_path_value(
                "maps.tile_url_template",
                "Tile provider URL template with {s}, {z}, {x} and {y} placeholders",
                "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
            )
        )
        subdomains = str(config.get_path_value("maps.tile_subdomains", "Subdomains for the {s} placeholder", "abc"))
        cls._subdomains = [char for char in subdomains if not char.isspace()] or ["a"]
        cls._subdomain_cycle = cycle(cls._subdomains)
        cls._ttl_days = float(
            config.get_path_value("maps.tile_ttl_days", "Days before a cached tile is re-fetched", 30)
        )
        megabytes = int(
            config.get_path_value("maps.tile_cache_mb", "Maximum tile cache size in MB (LRU eviction)", 1024)
        )
        cls._cache_bytes = megabytes * 1024 * 1024
        cls._folder.mkdir(parents=True, exist_ok=True)
        cls._evict()

    @classmethod
    async def get_tile(cls, z: int, x: int, y: int) -> Path | None:
        if cls._folder is None or not cls._valid(z, x, y):
            return None

        path = cls._tile_path(z, x, y)

        if path.exists() and not cls._expired(path):
            return path

        key = f"{z}/{x}/{y}"
        pending = cls._pending.get(key)

        if pending is not None:
            return await pending

        pending = asyncio.get_running_loop().create_future()
        cls._pending[key] = pending

        try:
            result = await cls._download(z, x, y, path)
            pending.set_result(result)
        except (OSError, requests.RequestException) as exception:
            result = path if path.exists() else None
            pending.set_result(result)
            cls._log(f"download failed for {key}: {exception}")
        except BaseException:
            # Leader cancelled (e.g. client disconnect): resolve waiters with stale data
            if not pending.done():
                pending.set_result(path if path.exists() else None)
            raise
        finally:
            cls._pending.pop(key, None)

        return result

    @classmethod
    async def _download(cls, z: int, x: int, y: int, path: Path) -> Path | None:
        url = cls._tile_url(z, x, y)

        try:
            response = await ThreadPoolService.run(lambda: requests.get(url, timeout=10, headers={"User-Agent": _USER_AGENT}))
        except requests.RequestException as exception:
            cls._log(f"fetch failed for {z}/{x}/{y}: {exception}")
            return path if path.exists() else None

        if response.status_code != 200:
            cls._log(f"fetch failed for {z}/{x}/{y}: HTTP {response.status_code}")
            return path if path.exists() else None

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(response.content)
        tmp.replace(path)

        cls._downloads_since_eviction += 1

        if cls._downloads_since_eviction >= _EVICTION_INTERVAL:
            cls._downloads_since_eviction = 0
            await ThreadPoolService.run(cls._evict)

        return path

    @classmethod
    def _valid(cls, z: int, x: int, y: int) -> bool:
        limit = 2**z
        return 0 <= z <= 18 and 0 <= x < limit and 0 <= y < limit

    @classmethod
    def _tile_path(cls, z: int, x: int, y: int) -> Path:
        return cls._folder / str(z) / str(x) / f"{y}.png"

    @classmethod
    def _tile_url(cls, z: int, x: int, y: int) -> str:
        return cls._url_template.format(s=next(cls._subdomain_cycle), z=z, x=x, y=y)

    @classmethod
    def _expired(cls, path: Path) -> bool:
        age = time.time() - path.stat().st_mtime
        return age > cls._ttl_days * 86400

    @classmethod
    def _evict(cls) -> None:
        if cls._folder is None:
            return

        entries: list[tuple[Path, float, int]] = []
        total = 0

        for root, _, files in os.walk(cls._folder):
            for file in files:
                file_path = Path(root) / file

                try:
                    stat = file_path.stat()
                except OSError:
                    continue

                entries.append((file_path, stat.st_mtime, stat.st_size))
                total += stat.st_size

        if total <= cls._cache_bytes:
            return

        entries.sort(key=lambda entry: entry[1])

        for file_path, _, size in entries:
            if total <= cls._cache_bytes:
                break

            try:
                file_path.unlink()
                total -= size
            except OSError:
                continue

        cls._log(f"evicted cache to {total // (1024 * 1024)} MB")
