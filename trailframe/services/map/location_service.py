import base64
import bisect
import json
import logging
import math
import re
import threading
import time
import tracemalloc
from collections import OrderedDict
from datetime import timedelta
from pathlib import Path
from typing import ClassVar

import requests
from shapely import STRtree, from_wkb, to_wkb
from shapely.errors import GEOSException
from shapely.geometry import MultiPolygon, Point, Polygon, shape

from trailframe.models.group import PhotoGroupSummary
from trailframe.models.photo import LocationEstimate, Photo
from trailframe.services.core.configuration_service import Node
from trailframe.services.core.thread_pool_service import ThreadPoolService
from trailframe.services.service import Service

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

_ESTIMATE_WINDOW = timedelta(days=1)
_MIN_INTERPOLATION_GAP = timedelta(minutes=1)
_MAX_INTERPOLATION_GAP = timedelta(hours=1)
_MAX_SPEED_KMH = 5.0
_MIN_RADIUS_M = 5_000.0
_MAX_RADIUS_M = 250_000.0


class _GeoIndex:
    """Boundary entries paired with an STRtree so point lookup only
    exact-tests the few candidates whose bounding box contains the point."""

    __slots__ = ("entries", "tree")

    def __init__(self, entries: list[tuple]) -> None:
        self.entries = entries
        self.tree = STRtree([geometry for geometry, _, _ in entries])


def _estimate_countries(rows: list[tuple]) -> dict[int, str]:
    """Country for photos without one, from the nearest dated photo within ±1 day."""
    sources = sorted(
        (photo_date, country) for _, photo_date, country, _, _ in rows if photo_date is not None and country is not None
    )
    dates = [photo_date for photo_date, _ in sources]
    window_s = _ESTIMATE_WINDOW.total_seconds()
    estimated: dict[int, str] = {}

    for photo_id, photo_date, country, _, _ in rows:
        if country is not None or photo_date is None:
            continue

        index = bisect.bisect_left(dates, photo_date)
        best: str | None = None
        best_delta: float | None = None

        if index < len(sources):
            candidate_date, candidate_country = sources[index]
            delta = abs((candidate_date - photo_date).total_seconds())

            if delta <= window_s:
                best = candidate_country
                best_delta = delta

        if index > 0:
            candidate_date, candidate_country = sources[index - 1]
            delta = abs((photo_date - candidate_date).total_seconds())

            if delta <= window_s and (best_delta is None or delta < best_delta):
                best = candidate_country

        if best is not None:
            estimated[photo_id] = best

    return estimated


def _find_discrepancies(rows: list[tuple]) -> set[int]:
    """Photos whose position deviates from the time-interpolated path between
    their nearest geotagged neighbors beyond the implied-speed bound."""
    geo = sorted(
        (photo_date, latitude, longitude, photo_id)
        for photo_id, photo_date, _, latitude, longitude in rows
        if photo_date is not None and latitude is not None and longitude is not None
    )
    min_gap_s = _MIN_INTERPOLATION_GAP.total_seconds()
    max_gap_s = _MAX_INTERPOLATION_GAP.total_seconds()
    discrepant: set[int] = set()

    for i, (photo_date, latitude, longitude, photo_id) in enumerate(geo):
        if i == 0 or i == len(geo) - 1:
            continue

        prev_date, prev_lat, prev_lon, _ = geo[i - 1]
        next_date, next_lat, next_lon, _ = geo[i + 1]
        span_s = (next_date - prev_date).total_seconds()

        if not (min_gap_s <= span_s <= max_gap_s):
            continue

        fraction = (photo_date - prev_date).total_seconds() / span_s
        expected_lat = prev_lat + fraction * (next_lat - prev_lat)
        expected_lon = prev_lon + fraction * (next_lon - prev_lon)
        deviation_m = LocationService.haversine(latitude, longitude, expected_lat, expected_lon)
        speed_kmh = deviation_m / 1000.0 / (span_s / 3600.0)

        if speed_kmh > _MAX_SPEED_KMH:
            discrepant.add(photo_id)

    return discrepant


def _compute_groups(rows: list[tuple]) -> list[PhotoGroupSummary]:
    """Group location-issue photos (estimated country or interpolated-path
    mismatch) by 'Year - Country'."""
    estimated = _estimate_countries(rows)
    discrepant = _find_discrepancies(rows)
    buckets: dict[tuple[int, str], list[int]] = {}

    for photo_id, photo_date, country, _, _ in rows:
        if photo_date is None:
            continue

        resolved = country if country is not None else estimated.get(photo_id)

        if resolved is None:
            continue

        if photo_id not in estimated and photo_id not in discrepant:
            continue

        buckets.setdefault((photo_date.year, resolved), []).append(photo_id)

    groups = [
        PhotoGroupSummary(name=f"{year} - {country}", automatic=True, photo_ids=sorted(photo_ids))
        for (year, country), photo_ids in buckets.items()
    ]
    groups.sort(key=lambda group: group.name)

    return groups


def _estimate_location(photo_id: int, rows: list[tuple]) -> LocationEstimate | None:
    """Estimated area for a photo without GPS whose country was guessed."""
    target = next((row for row in rows if row[0] == photo_id), None)

    if target is None:
        return None

    _, photo_date, country, latitude, longitude = target

    if country is not None or photo_date is None or (latitude is not None and longitude is not None):
        return None

    geo = [
        (row_date, row_lat, row_lon)
        for _, row_date, _, row_lat, row_lon in rows
        if row_date is not None and row_lat is not None and row_lon is not None and row_date != photo_date
    ]
    prev = None
    nxt = None

    for row_date, row_lat, row_lon in geo:
        if row_date <= photo_date:
            if prev is None or row_date > prev[0]:
                prev = (row_date, row_lat, row_lon)
        elif nxt is None or row_date < nxt[0]:
            nxt = (row_date, row_lat, row_lon)

    window_s = _ESTIMATE_WINDOW.total_seconds()

    if prev is not None and (photo_date - prev[0]).total_seconds() > window_s:
        prev = None

    if nxt is not None and (nxt[0] - photo_date).total_seconds() > window_s:
        nxt = None

    if prev is not None and nxt is not None:
        span_s = (nxt[0] - prev[0]).total_seconds()

        if span_s <= 0:
            return None

        fraction = (photo_date - prev[0]).total_seconds() / span_s
        center_lat = prev[1] + fraction * (nxt[1] - prev[1])
        center_lon = prev[2] + fraction * (nxt[2] - prev[2])
        radius_m = max(_MIN_RADIUS_M, LocationService.haversine(prev[1], prev[2], nxt[1], nxt[2]) / 2)
    elif prev is not None:
        center_lat, center_lon = prev[1], prev[2]
        gap_hours = (photo_date - prev[0]).total_seconds() / 3600.0
        radius_m = max(_MIN_RADIUS_M, min(_MAX_RADIUS_M, gap_hours * 10_000.0))
    elif nxt is not None:
        center_lat, center_lon = nxt[1], nxt[2]
        gap_hours = (nxt[0] - photo_date).total_seconds() / 3600.0
        radius_m = max(_MIN_RADIUS_M, min(_MAX_RADIUS_M, gap_hours * 10_000.0))
    else:
        return None

    return LocationEstimate(lat=center_lat, lon=center_lon, radius_m=round(radius_m))


class LocationService(Service):
    _requires = ("DatabaseService", "ThreadPoolService")
    _reconfig_safe = False

    _folder: Path | None = None
    _cache_folder: Path | None = None

    _adm0: _GeoIndex | None = None
    _adm1: ClassVar[OrderedDict[str, _GeoIndex]] = OrderedDict()
    _adm2: ClassVar[OrderedDict[str, _GeoIndex]] = OrderedDict()
    _lock = threading.Lock()

    _ADM_CACHE_SIZE = 16

    _VIEW = 512
    _PAD = 40
    _EARTH_RADIUS = 6378137.0
    _GEOBOUNDARIES_API = "https://www.geoboundaries.org/api/current/gbOpen"

    @staticmethod
    def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        radius = 6371000.0

        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2

        return 2 * radius * math.asin(math.sqrt(a))

    @classmethod
    def _configure(cls, config: Node) -> None:
        general_node = config.get_node("general", "General parameters")
        cls._folder = Path(general_node.get_path_value("maps_folder", "Folder where location maps are stored", "maps"))
        cls._cache_folder = cls._folder / "_cache"
        cls._folder.mkdir(parents=True, exist_ok=True)
        cls._cache_folder.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get_wireframe_path(cls, photo: Photo) -> Path | None:
        if cls._folder is None or not photo.wireframe:
            return None

        path = cls._folder / photo.wireframe

        return path if path.exists() else None

    @classmethod
    def get_wireframe_data(cls, photo: Photo) -> dict | None:
        if cls._folder is None or not photo.wireframe:
            return None

        path = cls._folder / photo.wireframe

        if not path.exists():
            return None

        data_path = path.with_suffix(".json")

        if not data_path.exists():
            return None

        try:
            return json.loads(data_path.read_text(encoding="utf-8"))
        except (ValueError, TypeError):
            return None

    @classmethod
    def locate(cls, lat: float, lon: float) -> tuple | None:
        point = Point(lon, lat)
        adm0 = cls._find(cls._get_adm0(), point)

        if adm0 is None:
            return None

        _, name, iso = adm0
        adm1 = cls._find(cls._get_adm(iso, 1), point)
        adm2 = cls._find(cls._get_adm(iso, 2), point)

        parts = [entry[1] for entry in (adm2, adm1) if entry is not None]
        parts.append(name)

        if adm2 is not None:
            level, units, focus = 2, cls._get_adm(iso, 2).entries, adm2
        elif adm1 is not None:
            level, units, focus = 1, cls._get_adm(iso, 1).entries, adm1
        else:
            level, units, focus = 0, cls._get_adm0().entries, adm0

        return name, ", ".join(parts), level, units, focus, list(reversed(parts))

    @classmethod
    def create_wireframe(cls, level: int, units: list[tuple], focus: tuple, file_parts: list[str]) -> str | None:
        if cls._folder is None:
            return None

        file_name = cls._file_name(file_parts) + ".svg"
        output = cls._folder / file_name

        if output.exists():
            return file_name

        focus_geometry = focus[0]
        transform, zoom, center_lat, center_lon, scale, cx, cy = cls._projection(focus_geometry)

        view = cls._viewport(scale, cx, cy, factor=1.0)
        tree = STRtree([geometry for geometry, _, _ in units])
        primary = [units[i] for i in sorted(tree.query(view))]

        paths: list[tuple[str, bool]] = []

        for geometry, _, _ in primary:
            is_focus = geometry is focus_geometry
            clipped = geometry.intersection(view)

            if clipped.is_empty:
                continue

            paths.append((cls._path(cls._project_rings(clipped, transform)), is_focus))

        output.write_text(cls._render(paths, level), encoding="utf-8")

        projection = {
            "width": cls._VIEW,
            "height": cls._VIEW,
            "zoom": zoom,
            "center": {"lat": center_lat, "lon": center_lon},
        }
        output.with_suffix(".json").write_text(json.dumps(projection), encoding="utf-8")

        return file_name

    @classmethod
    def _projection(cls, focus):
        return cls._projection_bounds(*cls._mercator_bounds(focus))

    @classmethod
    def _mercator_bounds(cls, geometry) -> tuple[float, float, float, float]:
        xs: list[float] = []
        ys: list[float] = []

        for x, y in cls._mercator_points(geometry):
            xs.append(x)
            ys.append(y)

        return min(xs), min(ys), max(xs), max(ys)

    @classmethod
    def _mercator_points(cls, geometry):
        if isinstance(geometry, Polygon):
            yield from cls._polygon_mercator_points(geometry)
        elif isinstance(geometry, MultiPolygon):
            for polygon in geometry.geoms:
                yield from cls._polygon_mercator_points(polygon)
        elif hasattr(geometry, "geoms"):
            for part in geometry.geoms:
                yield from cls._mercator_points(part)
        else:
            for lon, lat in geometry.coords:
                yield cls._mercator(lat, lon)

    @classmethod
    def _polygon_mercator_points(cls, polygon):
        for ring in (polygon.exterior, *polygon.interiors):
            for lon, lat in ring.coords:
                yield cls._mercator(lat, lon)

    @classmethod
    def _projection_bounds(cls, minx: float, miny: float, maxx: float, maxy: float):
        scale = (cls._VIEW - 2 * cls._PAD) / max(maxx - minx, maxy - miny)
        cx = (minx + maxx) / 2
        cy = (miny + maxy) / 2

        return cls._projection_at(scale, cx, cy)

    @classmethod
    def _projection_at(cls, scale: float, cx: float, cy: float):
        zoom = math.log2(2 * math.pi * cls._EARTH_RADIUS * scale / 256)
        center_lon, center_lat = cls._mercator_inverse(cx, cy)

        def transform(x: float, y: float) -> tuple[float, float]:
            return ((x - cx) * scale + cls._VIEW / 2, cls._VIEW / 2 - (y - cy) * scale)

        return transform, zoom, center_lat, center_lon, scale, cx, cy

    @classmethod
    def _viewport(cls, scale: float, cx: float, cy: float, factor: float = 1.0) -> Polygon:
        half = cls._VIEW / (2 * scale) * factor
        min_lon, min_lat = cls._mercator_inverse(cx - half, cy - half)
        max_lon, max_lat = cls._mercator_inverse(cx + half, cy + half)

        return Polygon(
            [(min_lon, min_lat), (max_lon, min_lat), (max_lon, max_lat), (min_lon, max_lat), (min_lon, min_lat)]
        )

    @classmethod
    def _project_rings(cls, geometry, transform) -> list[list[tuple[float, float]]]:
        rings: list[list[tuple[float, float]]] = []

        for ring in cls._rings(geometry):
            rings.append([transform(*coordinate) for coordinate in cls._mercator_ring(ring)])

        return rings

    @classmethod
    def _rings(cls, geometry):
        if isinstance(geometry, MultiPolygon):
            polygons = geometry.geoms
        else:
            polygons = [geometry]

        for polygon in polygons:
            if isinstance(polygon, Polygon):
                yield from (polygon.exterior, *polygon.interiors)

    @classmethod
    def _mercator_ring(cls, ring):
        return [cls._mercator(lat, lon) for lon, lat in ring.coords]

    @classmethod
    def _mercator(cls, lat: float, lon: float) -> tuple[float, float]:
        x = math.radians(lon) * cls._EARTH_RADIUS
        y = cls._EARTH_RADIUS * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))

        return x, y

    @classmethod
    def _mercator_inverse(cls, x: float, y: float) -> tuple[float, float]:
        lon = x / cls._EARTH_RADIUS * 180 / math.pi
        lat = (2 * math.atan(math.exp(y / cls._EARTH_RADIUS)) - math.pi / 2) * 180 / math.pi

        return lon, lat

    @staticmethod
    def _path(rings) -> str:
        parts = []

        for ring in rings:
            points = " ".join(f"{x:.1f},{y:.1f}" for x, y in ring)
            parts.append(f"M {points} Z")

        return " ".join(parts)

    @classmethod
    def _render(cls, paths: list[tuple[str, bool]], level: int) -> str:
        view = cls._VIEW
        stroke_width = {0: 2.5, 1: 1.8, 2: 1.2}
        elements: list[str] = []

        for path, is_focus in paths:
            fill = "rgba(0, 0, 0, 0.12)" if is_focus else "none"
            elements.append(
                f'  <path d="{path}" fill="{fill}" stroke="#1a1a1a" stroke-width="{stroke_width[level]}" '
                f'stroke-linejoin="round" opacity="0.85"/>'
            )

        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view} {view}">\n'
            + "\n".join(elements)
            + "\n</svg>\n"
        )

    @classmethod
    def _file_name(cls, parts: list[str]) -> str:
        return "_".join(cls._safe_part(part) for part in parts)

    @staticmethod
    def _safe_part(part: str) -> str:
        safe = _INVALID_FILENAME_CHARS.sub("_", part).strip(" .")
        safe = re.sub(r"\s+", "_", safe)

        return safe or "location"

    @classmethod
    def _timed_load(cls, label: str, loader):
        """Run a cache read or download, logging duration and peak memory at
        DEBUG. tracemalloc only traces the Python-side JSON churn (shapely's
        coordinate buffers live in numpy allocations it cannot see), so the
        geometry payload is reported separately via WKB size."""
        logger = logging.getLogger("LocationService")
        measure = logger.isEnabledFor(logging.DEBUG)
        already_tracing = False
        started = time.perf_counter()

        if measure:
            already_tracing = tracemalloc.is_tracing()

            if not already_tracing:
                tracemalloc.start()

        try:
            index = loader()

            if measure:
                _, peak = tracemalloc.get_traced_memory()
        finally:
            if measure and not already_tracing:
                tracemalloc.stop()

        if measure:
            wkb_bytes = sum(len(to_wkb(geometry)) for geometry, _, _ in index.entries)
            logger.debug(
                "%s: %d entries in %.2fs (traced peak %.1f MB, geometry %.1f MB)",
                label,
                len(index.entries),
                time.perf_counter() - started,
                peak / 1048576,
                wkb_bytes / 1048576,
            )

        return index

    @classmethod
    def _get_adm0(cls) -> _GeoIndex:
        if cls._adm0 is not None:
            return cls._adm0

        with cls._lock:
            if cls._adm0 is None:
                cls._adm0 = cls._timed_load("adm0", cls._load_adm0)

        return cls._adm0

    @classmethod
    def _load_adm0(cls) -> _GeoIndex:
        cache_file = cls._cache_folder / "adm0.jsonl"

        if cache_file.exists():
            cached = cls._read_entries(cache_file)

            if cached is not None:
                return _GeoIndex(cached)

        metadata = cls._fetch_json(f"{cls._GEOBOUNDARIES_API}/ALL/ADM0")

        if not metadata:
            return _GeoIndex([])

        # One country at a time: convert to shapely and drop the raw GeoJSON
        # immediately, so only a single raw structure is alive instead of all
        # ~250 at once (the original list(executor.map(...)) peak).
        entries: list[tuple] = []

        for boundary in metadata:
            url = boundary.get("simplifiedGeometryGeoJSON")

            if not url:
                continue

            geojson = cls._fetch_json(url)

            if not geojson:
                continue

            for feature in geojson.get("features", []):
                raw = feature.get("geometry")

                if not raw:
                    continue

                geometry = shape(raw)

                if geometry.is_empty:
                    continue

                properties = feature.get("properties") or {}
                entries.append(
                    (
                        geometry,
                        boundary.get("boundaryName") or properties.get("shapeName"),
                        properties.get("shapeISO") or boundary.get("boundaryISO"),
                    )
                )

            del geojson

        cls._write_entries(cache_file, entries)

        return _GeoIndex(entries)

    @classmethod
    def _get_adm(cls, iso: str, level: int) -> _GeoIndex:
        cache = cls._adm1 if level == 1 else cls._adm2

        index = cache.get(iso)

        if index is not None:
            with cls._lock:
                if iso in cache:
                    cache.move_to_end(iso)

            return index

        with cls._lock:
            index = cache.get(iso)

            if index is None:
                index = cls._timed_load(f"{iso.lower()}_adm{level}", lambda: cls._load_adm(iso, level))
                cache[iso] = index

                while len(cache) > cls._ADM_CACHE_SIZE:
                    cache.popitem(last=False)
            else:
                cache.move_to_end(iso)

        return index

    @classmethod
    def _load_adm(cls, iso: str, level: int) -> _GeoIndex:
        cache_file = cls._cache_folder / f"{iso.lower()}_adm{level}.jsonl"

        if cache_file.exists():
            cached = cls._read_entries(cache_file)

            if cached is not None:
                return _GeoIndex(cached)

        try:
            metadata = cls._fetch_json(f"{cls._GEOBOUNDARIES_API}/{iso}/ADM{level}")
        except (requests.HTTPError, ValueError):
            return _GeoIndex([])

        if not metadata or "simplifiedGeometryGeoJSON" not in metadata:
            return _GeoIndex([])

        geojson = cls._fetch_json(metadata["simplifiedGeometryGeoJSON"])

        if not geojson:
            return _GeoIndex([])

        entries = cls._parse_geojson(geojson)
        cls._write_entries(cache_file, entries)

        return _GeoIndex(entries)

    @classmethod
    def _fetch_json(cls, url: str):
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
        except requests.RequestException:
            return None

        try:
            return response.json()
        except ValueError:
            return None

    @classmethod
    def _parse_geojson(cls, geojson) -> list[tuple]:
        entries: list[tuple] = []

        for feature in geojson.get("features", []):
            raw = feature.get("geometry")

            if not raw:
                continue

            geometry = shape(raw)

            if geometry.is_empty:
                continue

            properties = feature.get("properties") or {}
            entries.append((geometry, properties.get("shapeName"), properties.get("shapeISO") or ""))

        return entries

    @classmethod
    def _read_entries(cls, path: Path) -> list[tuple] | None:
        """Stream a JSONL cache one entry per line: only the current raw entry
        and the growing shapely list are in memory, instead of the whole file
        text plus the fully parsed JSON structure (the old 300+ MB peak)."""
        entries: list[tuple] = []

        try:
            with path.open("r", encoding="utf-8") as file:
                for line in file:
                    if line.isspace():
                        continue

                    entry = json.loads(line)
                    entries.append((from_wkb(base64.b64decode(entry["geom"])), entry["name"], entry["iso"]))
        except (ValueError, KeyError, TypeError, OSError, GEOSException):
            return None

        # No parsed line: empty or truncated-by-interrupted-write file -> miss.
        return entries or None

    @classmethod
    def _write_entries(cls, path: Path, entries: list[tuple]) -> None:
        """Write JSONL+WKB line by line: no intermediate data list and no
        single giant joined string."""
        with path.open("w", encoding="utf-8") as file:
            for geometry, name, iso in entries:
                encoded = base64.b64encode(to_wkb(geometry)).decode("ascii")
                file.write(json.dumps({"name": name, "iso": iso, "geom": encoded}, ensure_ascii=False) + "\n")

        # Drop the pre-JSONL array cache (superseded format, no retrocompat).
        legacy = path.with_suffix(".json")

        if legacy.exists():
            legacy.unlink()

    @staticmethod
    def _find(index: _GeoIndex, point: Point):
        for candidate in index.tree.query(point):
            geometry, name, iso = index.entries[int(candidate)]

            if geometry.contains(point):
                return geometry, name, iso

        return None

    @classmethod
    async def get_groups(cls) -> list[PhotoGroupSummary]:
        """Location-issue groups: estimated-country or interpolated-path photos
        grouped by 'Year - Country'."""
        try:
            rows = await cls._fetch_photos()
            return await ThreadPoolService.run(_compute_groups, rows)
        except Exception:
            logging.getLogger("LocationService").exception("Failed to compute location issues")
            return []

    @classmethod
    async def get_estimate(cls, photo_id: int) -> LocationEstimate | None:
        rows = await cls._fetch_photos()
        return await ThreadPoolService.run(_estimate_location, photo_id, rows)

    @classmethod
    async def _fetch_photos(cls) -> list[tuple]:
        from sqlalchemy import select

        from trailframe.models.photo import Photo
        from trailframe.services.core.database_service import DatabaseService

        async def _fetch(session) -> list[tuple]:
            result = await session.execute(select(Photo.id, Photo.date, Photo.country, Photo.latitude, Photo.longitude))
            return [row for row in result.all()]

        return await DatabaseService.execute(_fetch)
