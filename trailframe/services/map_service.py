import math
import re
from pathlib import Path

import numpy as np
import s2sphere
import staticmaps
from s2sphere import LatLng

from trailframe.services.configuration_service import Node
from trailframe.services.service import Service


class MapService(Service):
    _folder: Path | None = None
    _margin: float | None = None

    _MAP_SIZE = 1500
    _MAP_PADDING = 20
    _TRACE_TOLERANCE = 2.0
    _TRACE_MAX_POINTS = 20000
    _INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

    @classmethod
    def _configure(cls, config: Node) -> None:
        cls._folder = Path(config.get_path_value("activities_folder", "Folder where activity maps are stored", "activities"))
        cls._margin = config.get_path_value("maps_margin", "Margins for the generated map", 0.1)
        cls._folder.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get_map(cls, activity: str) -> Path:
        return cls._folder / f"{cls._safe_name(activity)}_map.svg"

    @classmethod
    def get_trace(cls, activity: str) -> Path:
        return cls._folder / f"{cls._safe_name(activity)}_trace.svg"

    @classmethod
    def create_map(
        cls,
        activity: str,
        min_lat: float,
        min_lon: float,
        max_lat: float,
        max_lon: float,
    ) -> dict:
        if cls._folder is None:
            raise RuntimeError("MapService is not configured")

        margin = cls._margin or 0.0

        lat_span = max_lat - min_lat
        lon_span = max_lon - min_lon

        min_lat -= lat_span * margin + 0.0001
        max_lat += lat_span * margin + 0.0001
        min_lon -= lon_span * margin + 0.0001
        max_lon += lon_span * margin + 0.0001

        context = cls._context(min_lat, min_lon, max_lat, max_lon)

        output = cls.get_map(activity)
        image = context.render_svg(cls._MAP_SIZE, cls._MAP_SIZE)
        output.write_text(image.tostring(), encoding="utf-8")

        return cls._projection(min_lat, min_lon, max_lat, max_lon)

    @classmethod
    def create_trace(cls, activity: str, trace: list[dict], projection: dict) -> list[list[float]]:
        if cls._folder is None:
            raise RuntimeError("MapService is not configured")

        points = cls._project_trace(projection, trace)

        if len(points) < 2:
            return points

        path = " ".join(f"{px:.1f},{py:.1f}" for px, py in points)

        start_x, start_y = points[0]
        end_x, end_y = points[-1]

        size = cls._MAP_SIZE

        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">\n'
            f'  <polyline fill="none" stroke="#e53935" stroke-width="8" '
            f'stroke-linecap="round" stroke-linejoin="round" points="{path}"/>\n'
            f'{cls._pin(start_x, start_y, "#2e7d32", "START")}'
            f'{cls._pin(end_x, end_y, "#d32f2f", "STOP")}'
            f"</svg>\n"
        )

        output = cls.get_trace(activity)
        output.write_text(svg, encoding="utf-8")

        return points

    @classmethod
    def _context(cls, min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> staticmaps.Context:
        context = staticmaps.Context()
        context.set_tile_provider(staticmaps.tile_provider_OSM)
        context.add_bounds(
            s2sphere.LatLngRect.from_point_pair(
                staticmaps.create_latlng(min_lat, min_lon),
                staticmaps.create_latlng(max_lat, max_lon),
            ),
            extra_pixel_bounds=cls._MAP_PADDING,
        )

        return context

    @classmethod
    def _projection(cls, min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> dict:
        center, zoom = cls._context(min_lat, min_lon, max_lat, max_lon).determine_center_zoom(
            cls._MAP_SIZE, cls._MAP_SIZE
        )

        return {
            "width": cls._MAP_SIZE,
            "height": cls._MAP_SIZE,
            "zoom": zoom,
            "center": {"lat": center.lat().degrees, "lon": center.lng().degrees},
            "bounds": {
                "min_lat": min_lat,
                "min_lon": min_lon,
                "max_lat": max_lat,
                "max_lon": max_lon,
            },
        }

    @classmethod
    def _project_trace(cls, projection: dict, trace: list[dict]) -> list[list[float]]:
        transformer = staticmaps.transformer.Transformer(
            projection["width"],
            projection["height"],
            projection["zoom"],
            LatLng.from_degrees(projection["center"]["lat"], projection["center"]["lon"]),
            staticmaps.tile_provider_OSM.tile_size(),
        )

        points: list[tuple[float, float]] = []

        for point in trace:
            lat = point.get("lat")
            lon = point.get("lon")

            if lat is None or lon is None:
                continue

            px, py = transformer.ll2pixel(staticmaps.create_latlng(float(lat), float(lon)))
            points.append((px, py))

        if not points:
            return []

        if len(points) > cls._TRACE_MAX_POINTS:
            indices = np.linspace(0, len(points) - 1, cls._TRACE_MAX_POINTS).astype(int)
            points = [points[index] for index in indices]

        return [
            [float(px), float(py)] for px, py in cls._simplify(np.asarray(points), tolerance=cls._TRACE_TOLERANCE)
        ]

    @classmethod
    def _pin(cls, x: float, y: float, color: str, label: str) -> str:
        return (
            f'  <g transform="translate({x:.1f},{y:.1f})">\n'
            f'    <path d="M0,0 C-14,-20 -28,-34 -28,-50 A28,28 0 1,1 28,-50 C28,-34 14,-20 0,0 Z" '
            f'fill="{color}" stroke="white" stroke-width="4"/>\n'
            f'    <text x="0" y="-45" fill="white" font-family="Arial, sans-serif" font-size="15" '
            f'font-weight="bold" text-anchor="middle">{label}</text>\n'
            f"  </g>\n"
        )

    @classmethod
    def _simplify(cls, points: np.ndarray, tolerance: float) -> list[tuple[float, float]]:
        count = len(points)

        if count <= 2:
            return [(float(p[0]), float(p[1])) for p in points]

        keep = [False] * count
        keep[0] = True
        keep[-1] = True

        stack: list[tuple[int, int]] = [(0, count - 1)]

        while stack:
            start, end = stack.pop()

            if end - start <= 1:
                continue

            a = points[start]
            b = points[end]

            dx = b[0] - a[0]
            dy = b[1] - a[1]
            length_sq = dx * dx + dy * dy

            max_distance = 0.0
            farthest = start

            for index in range(start + 1, end):
                p = points[index]

                if length_sq == 0:
                    distance = math.hypot(p[0] - a[0], p[1] - a[1])
                else:
                    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length_sq
                    t = max(0.0, min(1.0, t))
                    distance = math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))

                if distance > max_distance:
                    max_distance = distance
                    farthest = index

            if max_distance > tolerance:
                keep[farthest] = True
                stack.append((start, farthest))
                stack.append((farthest, end))

        return [(float(points[i][0]), float(points[i][1])) for i in range(count) if keep[i]]

    @classmethod
    def _safe_name(cls, name: str) -> str:
        safe = cls._INVALID_FILENAME_CHARS.sub("_", str(name)).strip(" .")

        return safe or "activity"
