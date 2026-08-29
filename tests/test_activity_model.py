from __future__ import annotations

from datetime import UTC, datetime, timedelta

import allure
import pytest

from trailframe.models.activity import Activity, GarminActivity, GpxActivity


class TestActivityTrace:
    @allure.title("Parses a Garmin polyline and sorts points by time")
    def test_trace_parses_garmin_polyline_and_sorts(self):
        details = {
            "geoPolylineDTO": {
                "polyline": [
                    {"time": 3000, "lat": 1.0, "lon": 1.0},
                    {"time": 1000, "lat": 2.0, "lon": 2.0},
                    {"time": "2000", "lat": 3.0, "lon": 3.0},
                ]
            }
        }
        trace = Activity._trace(details)
        assert trace == [
            {"time": 1000, "lat": 2.0, "lon": 2.0},
            {"time": "2000", "lat": 3.0, "lon": 3.0},
            {"time": 3000, "lat": 1.0, "lon": 1.0},
        ]

    @allure.title("Skips points that are missing required fields")
    def test_trace_skips_incomplete_points(self):
        details = {
            "geoPolylineDTO": {
                "polyline": [
                    {"time": 1000, "lat": 1.0, "lon": 1.0},
                    {"time": None, "lat": 2.0, "lon": 2.0},
                    {"lat": 3.0, "lon": 3.0},
                    "not a dict",
                ]
            }
        }
        assert Activity._trace(details) == [{"time": 1000, "lat": 1.0, "lon": 1.0}]

    @allure.title("Returns an empty trace for malformed payloads")
    def test_trace_returns_empty_for_bad_shapes(self):
        assert Activity._trace(None) == []
        assert Activity._trace({}) == []
        assert Activity._trace({"geoPolylineDTO": {"polyline": "nope"}}) == []

    @allure.title("Converts seconds and milliseconds epochs correctly")
    def test_trace_epoch_handles_seconds_and_millis(self):
        assert Activity._trace_epoch("1600000000") == 1600000000
        assert Activity._trace_epoch(1600000000123) == 1600000000.123
        assert Activity._trace_epoch("nope") is None
        assert Activity._trace_epoch(None) is None

    @allure.title("Falls back to zero for unparseable timestamps when sorting")
    def test_trace_sort_key_falls_back_to_zero(self):
        assert Activity._trace_sort_key("10") == 10.0
        assert Activity._trace_sort_key("bad") == 0.0
        assert Activity._trace_sort_key(None) == 0.0


class TestInterpolateTrace:
    def _trace(self):
        return [{"time": 1600000000, "lat": 0.0, "lon": 0.0}, {"time": 1600001000, "lat": 2.0, "lon": 4.0}]

    @allure.title("Linearly interpolates a position between two trace points")
    def test_interpolates_midpoint(self):
        trace = self._trace()
        start = datetime.fromtimestamp(1600000000)
        photo = start + timedelta(seconds=500)
        result = Activity.interpolate_trace(trace, photo, start)
        assert result == pytest.approx((1.0, 2.0))

    @allure.title("Clamps to the first point when the photo predates the trace")
    def test_clamps_before_start(self):
        trace = self._trace()
        start = datetime.fromtimestamp(1600000000)
        photo = start - timedelta(seconds=10)
        assert Activity.interpolate_trace(trace, photo, start) == (0.0, 0.0)

    @allure.title("Clamps to the last point when the photo comes after the trace")
    def test_clamps_after_end(self):
        trace = self._trace()
        start = datetime.fromtimestamp(1600000000)
        photo = start + timedelta(seconds=2000)
        assert Activity.interpolate_trace(trace, photo, start) == (2.0, 4.0)

    @allure.title("Returns no position for an empty trace")
    def test_returns_none_on_empty_trace(self):
        start = datetime(2020, 1, 1)
        photo = start + timedelta(seconds=5)
        assert Activity.interpolate_trace([], photo, start) is None

    @allure.title("Returns no position when inputs are missing or invalid")
    def test_returns_none_when_missing_args(self):
        trace = self._trace()
        start = datetime(2020, 1, 1)
        photo = start + timedelta(seconds=1)
        assert Activity.interpolate_trace(trace, None, start) is None
        assert Activity.interpolate_trace(trace, photo, None) is None
        assert Activity.interpolate_trace(trace, "bad", start) is None


class TestGarminActivity:
    @allure.title("Builds an activity from a Garmin API payload")
    def test_from_data(self):
        data = {
            "activityId": 123,
            "activityName": "Morning Run",
            "startTimeLocal": "2023-06-01 08:30:00",
            "distance": 5000.0,
            "duration": 1800.0,
        }
        activity = GarminActivity.from_data(data)
        assert activity is not None
        assert activity.activityId == 123
        assert activity.activityName == "Morning Run"
        assert activity.distance == 5000.0
        assert activity.duration == 1800.0
        assert activity.startTimeLocal == datetime(2023, 6, 1, 8, 30, 0)

    @allure.title("Rejects payloads without an activity id")
    def test_from_data_returns_none_without_id(self):
        assert GarminActivity.from_data({}) is None

    @allure.title("Tolerates an unparseable start timestamp")
    def test_from_data_tolerates_bad_timestamp(self):
        data = {"activityId": 1, "startTimeLocal": "not-a-date"}
        activity = GarminActivity.from_data(data)
        assert activity is not None
        assert activity.startTimeLocal is None

    @allure.title("Converts a GarminActivity to an Activity")
    def test_to_activity(self):
        garmin = GarminActivity(
            activityId=55,
            activityName="Ride",
            startTimeLocal=datetime(2023, 6, 1, 8, 0, 0),
            distance=1000.0,
            duration=60.0,
            jsonActivity={"activityType": {"typeName": "Riding"}},
            jsonDetails={"geoPolylineDTO": {"polyline": [{"time": 1, "lat": 1.0, "lon": 1.0}]}},
        )
        activity = garmin.to_activity()
        assert activity.activity_id == "Garmin:55"
        assert activity.activity_type == "Riding"
        assert activity.trace == [{"time": 1, "lat": 1.0, "lon": 1.0}]


class TestGpxActivity:
    @allure.title("Parses a GPX track and computes duration and distance")
    def test_from_gpx_parses_track(self):
        gpx = """
        <gpx>
          <metadata><name>Trip</name></metadata>
          <trk>
            <name>Hike</name>
            <type>hiking</type>
            <trkseg>
              <trkpt lat="1.0" lon="2.0"><ele>100</ele><time>2023-06-01T08:00:00Z</time></trkpt>
              <trkpt lat="1.001" lon="2.001"><ele>101</ele><time>2023-06-01T08:00:30Z</time></trkpt>
            </trkseg>
          </trk>
        </gpx>
        """
        activity = GpxActivity.from_gpx(gpx, filename="my_run.gpx")
        assert activity is not None
        assert activity.name == "Hike"
        assert activity.activity_type == "hiking"
        assert activity.duration == 30.0
        assert activity.distance > 0
        assert len(activity.trace) == 2

        first = activity.trace[0]
        assert first["lat"] == 1.0
        assert first["lon"] == 2.0
        assert first["altitude"] == 100

    @allure.title("Falls back to the filename when the track has no name")
    def test_from_gpx_uses_filename_when_no_name(self):
        gpx = "<gpx><trk><trkseg><trkpt lat='1' lon='2'><time>2023-06-01T08:00:00Z</time></trkpt></trkseg></trk></gpx>"
        activity = GpxActivity.from_gpx(gpx, filename="trail.gpx")
        assert activity is not None
        assert activity.name == "trail"
        assert activity.activity_type is None

    @allure.title("Rejects invalid XML")
    def test_from_gpx_returns_none_on_invalid(self):
        assert GpxActivity.from_gpx("not xml", filename="x.gpx") is None

    @allure.title("Rejects a track without any points")
    def test_from_gpx_returns_none_without_points(self):
        assert GpxActivity.from_gpx("<gpx></gpx>", filename="x.gpx") is None

    @allure.title("Converts a GpxActivity to an Activity")
    def test_to_activity(self):
        activity = GpxActivity(
            id=7,
            name="Run",
            activity_type="running",
            start_time=datetime(2023, 6, 1, 8, 0, 0),
            distance=100.0,
            duration=10.0,
            trace=[{"time": 1, "lat": 1.0, "lon": 1.0}],
        )
        converted = activity.to_activity()
        assert converted.activity_id == "GPX:7"
        assert converted.name == "Run"
        assert converted.trace == activity.trace

    @allure.title("Computes haversine distances between coordinates")
    def test_haversine_known_distance(self):
        # Same point -> 0
        assert GpxActivity._haversine(0.0, 0.0, 0.0, 0.0) == 0.0
        # Roughly one degree of latitude ~ 111 km
        distance = GpxActivity._haversine(0.0, 0.0, 1.0, 0.0)
        assert 110000 < distance < 112000

    @allure.title("Parses timestamps, handling naive and timezone-aware values")
    def test_parse_time_handles_naive_and_aware(self):
        parsed = GpxActivity._parse_time("2023-06-01T08:00:00Z")
        assert parsed == datetime(2023, 6, 1, 8, 0, 0, tzinfo=UTC)
        naive = GpxActivity._parse_time("2023-06-01T08:00:00")
        assert naive.tzinfo is not None
        assert GpxActivity._parse_time("bad") is None
