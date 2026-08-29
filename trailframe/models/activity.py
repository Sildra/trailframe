from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from sqlmodel import JSON, Column, Field, SQLModel


class Activity(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)

    activity_id: str | None = Field(default=None, index=True, unique=True)
    name: str | None = None
    activity_type: str | None = None
    start_time: datetime | None = None
    duration: float | None = None
    distance: float | None = None
    trace: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    map_data: dict = Field(default_factory=dict, sa_column=Column(JSON))

    @classmethod
    def _trace(cls, details: dict | None) -> list[dict]:
        if not isinstance(details, dict):
            return []

        polyline_dto = details.get("geoPolylineDTO")

        if not isinstance(polyline_dto, dict):
            return []

        polyline = polyline_dto.get("polyline")

        if not isinstance(polyline, list):
            return []

        trace: list[dict] = []

        for point in polyline:
            if not isinstance(point, dict):
                continue

            time = point.get("time")
            lat = point.get("lat")
            lon = point.get("lon")

            if time is None or lat is None or lon is None:
                continue

            trace.append({"time": time, "lat": lat, "lon": lon})

        trace.sort(key=lambda point: cls._trace_sort_key(point["time"]))

        return trace

    @classmethod
    def _trace_sort_key(cls, time: object) -> float:
        try:
            return float(time)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def interpolate_trace(cls, trace: list[dict], photo_date, activity_start) -> tuple[float, float] | None:
        if not trace or photo_date is None or activity_start is None:
            return None

        anchor = cls._trace_epoch(trace[0].get("time"))

        if anchor is None:
            return None

        points: list[tuple[float, float, float]] = []

        for point in trace:
            epoch = cls._trace_epoch(point.get("time"))
            lat = point.get("lat")
            lon = point.get("lon")

            if epoch is None or lat is None or lon is None:
                continue

            points.append((epoch - anchor, float(lat), float(lon)))

        if not points:
            return None

        try:
            target = (photo_date - activity_start).total_seconds()
        except TypeError:
            return None

        if target <= points[0][0]:
            return points[0][1], points[0][2]

        if target >= points[-1][0]:
            return points[-1][1], points[-1][2]

        for index in range(1, len(points)):
            prev_time, prev_lat, prev_lon = points[index - 1]
            next_time, next_lat, next_lon = points[index]

            if target > next_time:
                continue

            span = next_time - prev_time
            fraction = 0.0 if span <= 0 else (target - prev_time) / span

            lat = prev_lat + (next_lat - prev_lat) * fraction
            lon = prev_lon + (next_lon - prev_lon) * fraction

            return lat, lon

        return None

    @classmethod
    def _trace_epoch(cls, value: object) -> float | None:
        if value is None:
            return None

        try:
            epoch = float(value)
        except (TypeError, ValueError):
            return None

        if epoch > 1e11:
            epoch /= 1000

        return epoch


class ActivitySummary(SQLModel):
    id: int | None = None
    activity_id: str | None = None
    name: str | None = None
    activity_type: str | None = None
    start_time: datetime | None = None
    duration: float | None = None
    distance: float | None = None
    photos: int = 0


class GarminActivity(SQLModel, table=True):
    __tablename__ = "garmin_activities"

    id: int | None = Field(default=None, primary_key=True)

    activityId: int | None = Field(default=None, index=True, unique=True)
    activityName: str | None = None
    startTimeLocal: datetime | None = None
    distance: float | None = None
    duration: float | None = None
    jsonActivity: dict = Field(default_factory=dict, sa_column=Column(JSON))
    jsonDetails: dict | None = Field(default=None, sa_column=Column(JSON))

    def to_activity(self) -> Activity:
        activity_type = None
        activity_type_data = self.jsonActivity.get("activityType")

        if isinstance(activity_type_data, dict):
            activity_type = activity_type_data.get("typeName")

        return Activity(
            activity_id=f"Garmin:{self.activityId}",
            name=self.activityName,
            activity_type=activity_type,
            start_time=self.startTimeLocal,
            duration=self.duration,
            distance=self.distance,
            trace=Activity._trace(self.jsonDetails),
        )

    @classmethod
    def from_data(cls, data: dict) -> GarminActivity | None:
        activity_id = data.get("activityId")

        if activity_id is None:
            return None

        start_value = data.get("startTimeLocal")
        start_time = None

        if start_value:
            try:
                start_time = datetime.strptime(start_value, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                start_time = None

        return cls(
            activityId=activity_id,
            activityName=data.get("activityName"),
            startTimeLocal=start_time,
            distance=data.get("distance"),
            duration=data.get("duration"),
            jsonActivity=data,
        )


class GarminActivitySummary(SQLModel):
    id: int | None = None
    activityId: int | None = None
    activityName: str | None = None
    startTimeLocal: datetime | None = None
    distance: float | None = None
    duration: float | None = None
    photos: int = 0
    imported: bool = False


class GpxActivity(SQLModel, table=True):
    __tablename__ = "gpx_activities"

    id: int | None = Field(default=None, primary_key=True)

    content_hash: str = Field(default="", index=True, unique=True)
    filename: str | None = None
    name: str | None = None
    activity_type: str | None = None
    start_time: datetime | None = None
    distance: float | None = None
    duration: float | None = None
    trace: list[dict] = Field(default_factory=list, sa_column=Column(JSON))

    def to_activity(self) -> Activity:
        return Activity(
            activity_id=f"GPX:{self.id}",
            name=self.name,
            activity_type=self.activity_type,
            start_time=self.start_time,
            duration=self.duration,
            distance=self.distance,
            trace=self.trace,
        )

    @classmethod
    def from_gpx(cls, content: str, filename: str | None = None) -> GpxActivity | None:
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            return None

        points: list[dict] = []

        for element in root.iter():
            if not isinstance(element.tag, str) or element.tag.rsplit("}", 1)[-1] != "trkpt":
                continue

            lat = element.get("lat")
            lon = element.get("lon")

            if lat is None or lon is None:
                continue

            try:
                lat = float(lat)
                lon = float(lon)
            except ValueError:
                continue

            ele: float | None = None
            time_value: str | None = None

            for child in element:
                if not isinstance(child.tag, str):
                    continue

                tag = child.tag.rsplit("}", 1)[-1]

                if tag == "ele":
                    try:
                        ele = float((child.text or "").strip())
                    except ValueError:
                        ele = None
                elif tag == "time":
                    time_value = (child.text or "").strip()

            points.append({"lat": lat, "lon": lon, "ele": ele, "time": time_value})

        if not points:
            return None

        distance = 0.0

        for index in range(1, len(points)):
            distance += cls._haversine(
                points[index - 1]["lat"], points[index - 1]["lon"], points[index]["lat"], points[index]["lon"]
            )

        parsed_times: list[datetime] = []
        trace: list[dict] = []

        for point in points:
            if not point["time"]:
                continue

            parsed = cls._parse_time(point["time"])

            if parsed is None:
                continue

            parsed_times.append(parsed)

            entry: dict = {"time": int(parsed.timestamp() * 1000), "lat": point["lat"], "lon": point["lon"]}

            if point["ele"] is not None:
                entry["altitude"] = point["ele"]

            trace.append(entry)

        if not parsed_times:
            return None

        trace.sort(key=lambda entry: entry["time"])

        start_time = min(parsed_times)
        end_time = max(parsed_times)

        duration = (end_time - start_time).total_seconds()
        start_time = start_time.astimezone(UTC).replace(tzinfo=None)

        name, activity_type = cls._meta(root, filename)

        return cls(
            name=name,
            activity_type=activity_type,
            start_time=start_time,
            distance=distance,
            duration=duration,
            trace=trace,
        )

    @classmethod
    def _meta(cls, root: ET.Element, filename: str | None) -> tuple[str | None, str | None]:
        name: str | None = None
        activity_type: str | None = None

        for element in root.iter():
            if not isinstance(element.tag, str) or element.tag.rsplit("}", 1)[-1] != "trk":
                continue

            for child in element:
                if not isinstance(child.tag, str):
                    continue

                tag = child.tag.rsplit("}", 1)[-1]

                if tag == "name" and name is None:
                    name = (child.text or "").strip() or None
                elif tag == "type" and activity_type is None:
                    activity_type = (child.text or "").strip() or None

        if name is None:
            for element in root.iter():
                if not isinstance(element.tag, str) or element.tag.rsplit("}", 1)[-1] != "metadata":
                    continue

                for child in element:
                    if not isinstance(child.tag, str):
                        continue

                    if child.tag.rsplit("}", 1)[-1] == "name":
                        name = (child.text or "").strip() or None
                        break

                break

        if name is None and filename:
            name = Path(filename).stem

        return name, activity_type

    @staticmethod
    def _parse_time(value: str) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)

        return parsed

    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        radius = 6371000.0

        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2

        return 2 * radius * math.asin(math.sqrt(a))


class GpxActivitySummary(SQLModel):
    id: int | None = None
    filename: str | None = None
    name: str | None = None
    activity_type: str | None = None
    start_time: datetime | None = None
    distance: float | None = None
    duration: float | None = None
    photos: int = 0
    imported: bool = False
