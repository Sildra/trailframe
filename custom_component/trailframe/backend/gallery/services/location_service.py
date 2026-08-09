import json
import math
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import ClassVar

import requests
from shapely.geometry import MultiPolygon, Point, Polygon, shape

from gallery.models.photo import Photo
from gallery.services.configuration_service import Node
from gallery.services.service import Service

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class LocationService(Service):
    _folder: Path | None = None
    _cache_folder: Path | None = None

    _adm0: list[tuple] | None = None
    _adm1: ClassVar[dict[str, list[tuple]]] = {}
    _adm2: ClassVar[dict[str, list[tuple]]] = {}
    _lock = threading.Lock()

    _VIEW = 512
    _PAD = 40
    _EARTH_RADIUS = 6378137.0
    _GEOBOUNDARIES_API = "https://www.geoboundaries.org/api/current/gbOpen"

    @classmethod
    def _configure(cls, config: Node) -> None:
        cls._folder = Path(
            config.get_path_value("maps_folder", "Folder where location maps are stored", "maps")
        )
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
            level, units, focus = 2, cls._get_adm(iso, 2), adm2
        elif adm1 is not None:
            level, units, focus = 1, cls._get_adm(iso, 1), adm1
        else:
            level, units, focus = 0, cls._get_adm0(), adm0

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
        primary = [u for u in units if u[0].intersects(view)]

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
            [
                (min_lon, min_lat),
                (max_lon, min_lat),
                (max_lon, max_lat),
                (min_lon, max_lat),
                (min_lon, min_lat),
            ]
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
    def _get_adm0(cls) -> list[tuple]:
        if cls._adm0 is not None:
            return cls._adm0

        with cls._lock:
            if cls._adm0 is None:
                cls._adm0 = cls._load_adm0()

        return cls._adm0

    @classmethod
    def _load_adm0(cls) -> list[tuple]:
        cache_file = cls._cache_folder / "adm0.json"

        if cache_file.exists():
            cached = cls._read_entries(cache_file)

            if cached is not None:
                return cached

        metadata = cls._fetch_json(f"{cls._GEOBOUNDARIES_API}/ALL/ADM0")

        if not metadata:
            return []

        urls = [entry["simplifiedGeometryGeoJSON"] for entry in metadata]
        geojsons = cls._fetch_geojsons(urls)
        entries: list[tuple] = []

        for entry, geojson in zip(metadata, geojsons):
            if not geojson:
                continue

            for feature in geojson.get("features", []):
                geometry = shape(feature.get("geometry"))

                if geometry is None or geometry.is_empty:
                    continue

                properties = feature.get("properties") or {}
                entries.append(
                    (
                        geometry,
                        entry.get("boundaryName") or properties.get("shapeName"),
                        properties.get("shapeISO") or entry.get("boundaryISO"),
                    )
                )

        cls._write_entries(cache_file, entries)

        return entries

    @classmethod
    def _get_adm(cls, iso: str, level: int) -> list[tuple]:
        cache = cls._adm1 if level == 1 else cls._adm2

        if iso in cache:
            return cache[iso]

        with cls._lock:
            if iso not in cache:
                cache[iso] = cls._load_adm(iso, level)

        return cache[iso]

    @classmethod
    def _load_adm(cls, iso: str, level: int) -> list[tuple]:
        cache_file = cls._cache_folder / f"{iso.lower()}_adm{level}.json"

        if cache_file.exists():
            cached = cls._read_entries(cache_file)

            if cached is not None:
                return cached

        try:
            metadata = cls._fetch_json(f"{cls._GEOBOUNDARIES_API}/{iso}/ADM{level}")
        except (requests.HTTPError, ValueError):
            return []

        if not metadata or "simplifiedGeometryGeoJSON" not in metadata:
            return []

        geojson = cls._fetch_json(metadata["simplifiedGeometryGeoJSON"])
        entries = cls._parse_geojson(geojson)
        cls._write_entries(cache_file, entries)

        return entries

    @classmethod
    def _fetch_geojsons(cls, urls: list[str]) -> list[dict | None]:
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(cls._fetch_json, urls))

        return results

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
            geometry = shape(feature.get("geometry"))

            if geometry is None or geometry.is_empty:
                continue

            properties = feature.get("properties") or {}
            entries.append(
                (
                    geometry,
                    properties.get("shapeName"),
                    properties.get("shapeISO") or "",
                )
            )

        return entries

    @classmethod
    def _read_entries(cls, path: Path) -> list[tuple] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return [(shape(entry["geometry"]), entry["name"], entry["iso"]) for entry in data]
        except (ValueError, KeyError, TypeError):
            return None

    @classmethod
    def _write_entries(cls, path: Path, entries: list[tuple]) -> None:
        data = [
            {"geometry": geometry.__geo_interface__, "name": name, "iso": iso}
            for geometry, name, iso in entries
        ]
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _find(entries: list[tuple], point: Point):
        for geometry, name, iso in entries:
            if geometry.contains(point):
                return geometry, name, iso

        return None
