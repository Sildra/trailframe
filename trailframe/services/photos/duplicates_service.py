import logging
import threading
from pathlib import Path
from typing import ClassVar

import numpy as np

from trailframe.services.core.configuration_service import Node
from trailframe.services.core.thread_pool_service import ThreadPoolService
from trailframe.services.service import Service

THRESHOLD = 8
_DELTA_LIMIT = 64
_NUMPY_CHUNK = 256
_PHASH_LENGTH = 8


def _parse_phash(raw: bytes | str | None) -> int | None:
    """Convert raw phash storage to a 64-bit integer, or ``None`` on failure.

    Handles both the current 8-byte bit-packed format and the legacy 64-byte
    per-bit format (each byte is 0x00 or 0x01) produced by earlier iterations.
    """

    if isinstance(raw, memoryview):
        raw = bytes(raw)

    if not isinstance(raw, (bytes, bytearray)):
        return None

    if len(raw) == 8:
        return int.from_bytes(raw, "big")

    if len(raw) == 64 and all(byte in (0, 1) for byte in raw):
        value = 0
        for byte in raw:
            value = (value << 1) | byte
        return value

    return None


class DuplicatesService(Service):
    """Master cache of duplicate photo clusters.

    Duplicate clusters (pHash distance < 8, connected components) are computed
    once and cached in memory. Mutations are recorded as cheap deltas and
    applied lazily on the next read:

    - `mark_added(photo_id, phash)` — a photo got a fresh perceptual hash.
    - `mark_deleted(photo_id)` — a photo was removed.

    Cluster computation runs in the shared worker pool (numpy vectorized
    bit-count scan), keeping the SQL `hamming()` function (a Python call per
    pair) and any DB locking out of the hot path. The cache is tied to the
    current database file: switching DBs resets it.
    """

    _name = "Duplicates"

    _lock: ClassVar[threading.Lock] = threading.Lock()
    _db_path: ClassVar[Path | None] = None
    _clusters: ClassVar[dict[int, set[int]] | None] = None
    _membership: ClassVar[dict[int, int]] = {}
    _phashes: ClassVar[dict[int, int]] = {}
    _pending_adds: ClassVar[dict[int, int]] = {}
    _pending_deletes: ClassVar[set[int]] = set()

    @classmethod
    def _configure(cls, config: Node) -> None:
        pass

    @classmethod
    def mark_added(cls, photo_id: int | None, phash: bytes | None) -> None:
        if photo_id is None or phash is None:
            return

        value = _parse_phash(phash)

        if value is None:
            return

        with cls._lock:
            cls._pending_deletes.discard(photo_id)
            cls._pending_adds[photo_id] = value

    @classmethod
    def mark_deleted(cls, photo_id: int) -> None:
        with cls._lock:
            cls._pending_adds.pop(photo_id, None)
            cls._pending_deletes.add(photo_id)

    @classmethod
    async def get_clusters(cls) -> list[list[int]]:
        """Return the current duplicate clusters (list of photo-id lists)."""
        try:
            return await cls._get_clusters()
        except Exception:
            logging.getLogger("DuplicatesService").exception("Failed to compute duplicate clusters")
            return []

    @classmethod
    async def _get_clusters(cls) -> list[list[int]]:
        with cls._lock:
            cls._check_database_locked()

            if cls._clusters is None or len(cls._pending_adds) > _DELTA_LIMIT:
                rebuild = True
            else:
                rebuild = False

        if rebuild:
            rows = await cls._fetch_hashes()
            computed = await ThreadPoolService.run(cls._compute_clusters, rows)

            with cls._lock:
                cls._check_database_locked()
                cls._clusters = computed
                cls._membership = {member_id: root_id for root_id, members in computed.items() for member_id in members}
                cls._phashes = {}
                for photo_id, raw in rows:
                    value = _parse_phash(raw)

                    if value is not None:
                        cls._phashes[photo_id] = value

        with cls._lock:
            cls._check_database_locked()
            cls._apply_pending_locked()

        with cls._lock:
            cls._check_database_locked()
            clusters = [sorted(members) for members in cls._clusters.values() if len(members) >= 2]

        return clusters

    @classmethod
    async def _fetch_hashes(cls) -> list[tuple[int, bytes]]:
        from sqlalchemy import select

        from trailframe.models.photo import Photo
        from trailframe.services.core.database_service import DatabaseService

        async def _fetch(session) -> list[tuple[int, bytes]]:
            result = await session.execute(select(Photo.id, Photo.phash).where(Photo.phash.isnot(None)))
            return [(row[0], row[1]) for row in result.all()]

        return await DatabaseService.execute(_fetch)

    @classmethod
    def _check_database_locked(cls) -> None:
        from trailframe.services.core.database_service import DatabaseService

        path = DatabaseService.get_database_path()

        if cls._db_path != path:
            cls._db_path = path
            cls._clusters = None
            cls._membership = {}
            cls._phashes = {}
            cls._pending_adds = {}
            cls._pending_deletes = set()

    @classmethod
    def _apply_pending_locked(cls) -> None:
        if cls._clusters is None:
            return

        for photo_id in cls._pending_deletes:
            cls._remove_photo_locked(photo_id)

        for photo_id, phash in cls._pending_adds.items():
            cls._add_photo_locked(photo_id, phash)

        cls._pending_deletes = set()
        cls._pending_adds = {}

    @classmethod
    def _add_photo_locked(cls, photo_id: int, phash: int) -> None:
        if cls._phashes.get(photo_id) == phash:
            return

        cls._remove_photo_locked(photo_id)

        neighbors = [
            other_id for other_id, other_hash in cls._phashes.items() if (other_hash ^ phash).bit_count() < THRESHOLD
        ]

        cls._phashes[photo_id] = phash

        if not neighbors:
            return

        roots = {cls._membership[neighbor] for neighbor in neighbors if neighbor in cls._membership}
        loose = [neighbor for neighbor in neighbors if neighbor not in cls._membership]

        if not roots:
            members = {photo_id, *loose}
            cls._clusters[photo_id] = members
            for member_id in members:
                cls._membership[member_id] = photo_id
            return

        target = min(roots)
        members = cls._clusters[target] | {photo_id} | set(loose)

        for root in roots:
            if root == target:
                continue
            members |= cls._clusters[root]
            del cls._clusters[root]

        cls._clusters[target] = members

        for member_id in members:
            cls._membership[member_id] = target

    @classmethod
    def _remove_photo_locked(cls, photo_id: int) -> None:
        root = cls._membership.pop(photo_id, None)

        if root is not None and root in cls._clusters:
            cluster = cls._clusters[root]
            cluster.discard(photo_id)

            if len(cluster) < 2:
                del cls._clusters[root]
                for member_id in cluster:
                    cls._membership.pop(member_id, None)

        cls._phashes.pop(photo_id, None)

    @classmethod
    def _compute_clusters(cls, rows: list[tuple[int, bytes]]) -> dict[int, set[int]]:
        pairs = []

        for photo_id, raw in rows:
            value = _parse_phash(raw)

            if value is not None:
                pairs.append((photo_id, value))

        if not pairs:
            return {}

        pairs.sort(key=lambda p: p[0])
        ids = [pid for pid, _ in pairs]
        arr = np.array([v for _, v in pairs], dtype=np.uint64)
        n = len(arr)

        parent: dict[int, int] = {}

        def _find(node: int) -> int:
            while parent[node] != node:
                parent[node] = parent[parent[node]]
                node = parent[node]
            return node

        for i in range(0, n, _NUMPY_CHUNK):
            dist = np.bitwise_count(arr[i : i + _NUMPY_CHUNK, None] ^ arr[None, :])

            for r in range(len(dist)):
                left_id = ids[i + r]
                parent.setdefault(left_id, left_id)

                near = np.nonzero(dist[r, i + r + 1 :] < THRESHOLD)[0]

                for c in near:
                    right_id = ids[i + r + 1 + c]
                    parent.setdefault(right_id, right_id)
                    root_a = _find(left_id)
                    root_b = _find(right_id)

                    if root_a != root_b:
                        parent[root_b] = root_a

        clusters: dict[int, set[int]] = {}

        for node in parent:
            root = _find(node)
            clusters.setdefault(root, set()).add(node)

        return clusters
