from __future__ import annotations

import base64
import json
import math
import tracemalloc
from collections import OrderedDict

import allure
import pytest
from shapely import to_wkb
from shapely.geometry import MultiPolygon, Point, Polygon, mapping

from trailframe.services.map.location_service import LocationService, _GeoIndex


@pytest.fixture(autouse=True)
def clean_location_state(tmp_path, monkeypatch):
    """Isolate the class-level caches from other tests (and the real data dir),
    and fail fast on any accidental live network call."""
    cache = tmp_path / "cache"
    cache.mkdir()

    LocationService._folder = None
    LocationService._cache_folder = cache
    LocationService._adm0 = None
    LocationService._adm1 = OrderedDict()
    LocationService._adm2 = OrderedDict()
    LocationService._download = None

    monkeypatch.setattr(LocationService, "_fetch_json", staticmethod(lambda url: pytest.fail(f"network call: {url}")))

    yield

    LocationService._folder = None
    LocationService._cache_folder = None
    LocationService._adm0 = None
    LocationService._adm1 = OrderedDict()
    LocationService._adm2 = OrderedDict()
    LocationService._download = None


def _square(lon: float, lat: float, size: float = 1.0) -> Polygon:
    return Polygon([(lon, lat), (lon + size, lat), (lon + size, lat + size), (lon, lat + size), (lon, lat)])


def _blob(cx: float, cy: float, points: int = 400, radius: float = 0.4) -> Polygon:
    return Polygon(
        [
            (cx + radius * math.cos(2 * math.pi * i / points), cy + radius * math.sin(2 * math.pi * i / points))
            for i in range(points)
        ]
    )


def _mock_fetch(monkeypatch, responses: dict):
    calls: list[str] = []

    def fake_fetch(url):
        calls.append(url)

        if url not in responses:
            raise AssertionError(f"unexpected url {url}")

        return responses[url]

    monkeypatch.setattr(LocationService, "_fetch_json", staticmethod(fake_fetch))
    return calls


@allure.feature("Location cache format")
class TestCacheFormat:
    def test_round_trip_preserves_entries(self, tmp_path):
        path = tmp_path / "adm.jsonl"
        entries = [
            (_square(0, 0), "Île de France", "FR"),
            (MultiPolygon([_square(10, 10), _square(20, 20)]), "Côte d'Azur", ""),
            (_blob(5, 5), None, "XX-01"),
        ]

        LocationService._write_entries(path, entries)
        loaded = LocationService._read_entries(path)

        assert loaded is not None
        assert len(loaded) == len(entries)

        for (read_geometry, read_name, read_iso), (geometry, name, iso) in zip(loaded, entries):
            assert read_name == name
            assert read_iso == iso
            assert to_wkb(read_geometry) == to_wkb(geometry)

    def test_garbage_content_is_cache_miss(self, tmp_path):
        path = tmp_path / "adm.jsonl"
        path.write_text("not jsonl {{{", encoding="utf-8")
        assert LocationService._read_entries(path) is None

    def test_truncated_last_line_is_cache_miss(self, tmp_path):
        path = tmp_path / "adm.jsonl"
        LocationService._write_entries(path, [(_square(0, 0), "Ok", "OK")])
        with path.open("a", encoding="utf-8") as file:
            file.write('{"name": "Cut", "iso":')
        assert LocationService._read_entries(path) is None

    def test_invalid_wkb_is_cache_miss(self, tmp_path):
        path = tmp_path / "adm.jsonl"
        line = {"name": "Bad", "iso": "BAD", "geom": base64.b64encode(b"not a wkb").decode("ascii")}
        path.write_text(json.dumps(line) + "\n", encoding="utf-8")
        assert LocationService._read_entries(path) is None

    def test_empty_file_is_cache_miss(self, tmp_path):
        """An interrupted write truncates the file: it must not count as a
        valid empty cache (which would suppress re-downloading forever)."""
        path = tmp_path / "adm.jsonl"
        path.write_text("", encoding="utf-8")
        assert LocationService._read_entries(path) is None

        path.write_text("\n\n", encoding="utf-8")
        assert LocationService._read_entries(path) is None


@allure.feature("Location cache memory")
class TestPeakMemory:
    def test_read_transient_stays_below_retained(self, tmp_path):
        """The streaming reader must never hold a file-wide copy (text or
        parsed JSON) next to the shapely entries: transient Python allocations
        stay under the retained ones. The old whole-array reader peaked at
        file + parsed structure (measured 311 MB on real data) and fails this
        bound by orders of magnitude."""
        path = tmp_path / "adm0.jsonl"
        entries = [(_blob(i % 20, i // 20), f"Region {i}", f"XX-{i:03d}") for i in range(500)]
        LocationService._write_entries(path, entries)

        tracing = tracemalloc.is_tracing()
        if not tracing:
            tracemalloc.start()

        try:
            tracemalloc.reset_peak()
            before, _ = tracemalloc.get_traced_memory()
            loaded = LocationService._read_entries(path)
            current, peak = tracemalloc.get_traced_memory()
        finally:
            if not tracing:
                tracemalloc.stop()

        assert loaded is not None
        assert len(loaded) == 500

        retained = current - before
        transient = peak - current
        assert retained > 0
        assert transient <= 0.75 * retained, f"transient {transient} B vs retained {retained} B"


@allure.feature("Location cache download")
class TestDownload:
    def test_missing_cache_downloads_and_writes_jsonl(self, tmp_path, monkeypatch):
        # A leftover cache from the pre-JSONL array format must be dropped.
        legacy = tmp_path / "cache" / "xx_adm1.json"
        legacy.write_text("[]", encoding="utf-8")

        square = _square(0, 0)
        responses = {
            "https://example.test/geo.json": {
                "features": [
                    {
                        "type": "Feature",
                        "geometry": mapping(square),
                        "properties": {"shapeName": "Region", "shapeISO": "XX-01"},
                    }
                ]
            },
            f"{LocationService._GEOBOUNDARIES_API}/XX/ADM1": {
                "simplifiedGeometryGeoJSON": "https://example.test/geo.json"
            },
        }
        calls = _mock_fetch(monkeypatch, responses)

        index = LocationService._get_adm("XX", 1)

        assert [entry[1] for entry in index.entries] == ["Region"]
        assert len(calls) == 2

        cache_file = tmp_path / "cache" / "xx_adm1.jsonl"
        read_back = LocationService._read_entries(cache_file)
        assert read_back is not None
        assert read_back[0][1] == "Region"
        assert not legacy.exists()

    def test_garbage_cache_is_redownloaded_and_overwritten(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "cache" / "xx_adm1.jsonl"
        cache_file.write_text("garbage {{{", encoding="utf-8")

        _mock_fetch(
            monkeypatch,
            {
                f"{LocationService._GEOBOUNDARIES_API}/XX/ADM1": {
                    "simplifiedGeometryGeoJSON": "https://example.test/geo.json"
                },
                "https://example.test/geo.json": {
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": mapping(_square(0, 0)),
                            "properties": {"shapeName": "Fresh", "shapeISO": "XX-01"},
                        }
                    ]
                },
            },
        )

        index = LocationService._load_adm("XX", 1)

        assert [entry[1] for entry in index.entries] == ["Fresh"]
        assert LocationService._read_entries(cache_file)[0][1] == "Fresh"

    def test_adm0_download_is_sequential(self, monkeypatch):
        """One raw GeoJSON at a time: the old parallel fetch kept every raw
        structure alive at once."""
        assert not hasattr(LocationService, "_fetch_geojsons")

        active = 0
        max_active = 0

        def fake_fetch(url):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)

            try:
                if url.endswith("/ALL/ADM0"):
                    return [
                        {"simplifiedGeometryGeoJSON": f"https://example.test/{i}.json", "boundaryName": f"Country{i}"}
                        for i in range(5)
                    ]

                index = int(url.rsplit("/", 1)[1].split(".")[0])
                return {
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": mapping(_square(index * 2, 0)),
                            "properties": {"shapeISO": f"C{index}"},
                        }
                    ]
                }
            finally:
                active -= 1

        monkeypatch.setattr(LocationService, "_fetch_json", staticmethod(fake_fetch))

        index = LocationService._get_adm0()

        assert len(index.entries) == 5
        assert max_active == 1
        assert (LocationService._cache_folder / "adm0.jsonl").exists()

    def test_adm0_fetch_failure_returns_empty_index(self, monkeypatch):
        _mock_fetch(monkeypatch, {f"{LocationService._GEOBOUNDARIES_API}/ALL/ADM0": None})

        assert LocationService._load_adm0().entries == []


@allure.feature("Location adm cache LRU")
class TestAdmLru:
    @pytest.fixture()
    def loaded_isos(self, monkeypatch):
        calls: list[str] = []

        def fake_load(cls, iso: str, level: int):
            calls.append(iso)
            return _GeoIndex([(_square(0, 0), iso, iso)])

        monkeypatch.setattr(LocationService, "_load_adm", classmethod(fake_load))
        return calls

    def test_evicts_beyond_limit(self, loaded_isos):
        limit = LocationService._ADM_CACHE_SIZE

        for i in range(limit + 1):
            LocationService._get_adm(f"X{i:02d}", 1)

        assert len(LocationService._adm1) == limit
        assert "X00" not in LocationService._adm1
        assert f"X{limit:02d}" in LocationService._adm1

    def test_cached_hit_does_not_reload_and_recency_protects(self, loaded_isos):
        limit = LocationService._ADM_CACHE_SIZE

        for i in range(limit):
            LocationService._get_adm(f"Y{i:02d}", 1)

        # Touch the oldest entry so it becomes the most recent one.
        LocationService._get_adm("Y00", 1)
        assert loaded_isos.count("Y00") == 1

        LocationService._get_adm("Ynew", 1)

        assert len(LocationService._adm1) == limit
        assert "Y00" in LocationService._adm1
        assert "Y01" not in LocationService._adm1
        assert loaded_isos.count("Y00") == 1


@allure.feature("Location point lookup")
class TestFind:
    def test_finds_containing_entry_among_many(self):
        entries = [(_square(i % 10, i // 10), f"Cell {i}", f"I{i}") for i in range(100)]
        index = _GeoIndex(entries)

        found = LocationService._find(index, Point(7.5, 3.5))
        assert found is not None
        assert found[1] == "Cell 37"

        assert LocationService._find(index, Point(-5.0, -5.0)) is None


@allure.feature("Location locate")
class TestLocate:
    @pytest.fixture()
    def warm_cache(self, tmp_path):
        cache = LocationService._cache_folder
        country = _square(0, 0, size=3.0)
        LocationService._write_entries(cache / "adm0.jsonl", [(country, "Country", "ZZ")])
        LocationService._write_entries(cache / "zz_adm1.jsonl", [(_square(0, 0, size=2.0), "Region", "ZZ-01")])
        LocationService._write_entries(cache / "zz_adm2.jsonl", [(_square(0, 0, size=1.0), "District", "ZZ-01-01")])

    def test_locate_from_cache_without_network(self, warm_cache):
        result = LocationService.locate(0.5, 0.5)

        assert result is not None
        name, full, level, units, focus, file_parts = result
        assert name == "Country"
        assert full == "District, Region, Country"
        assert level == 2
        assert len(units) == 1
        assert focus[1] == "District"
        assert file_parts == ["Country", "Region", "District"]

    def test_locate_falls_back_to_country_only(self, warm_cache, monkeypatch):
        (LocationService._cache_folder / "zz_adm1.jsonl").unlink()
        (LocationService._cache_folder / "zz_adm2.jsonl").unlink()
        # Missing per-country cache would normally fetch: answer "no data"
        # instead of hitting the live geoboundaries API.
        monkeypatch.setattr(LocationService, "_fetch_json", staticmethod(lambda url: None))

        result = LocationService.locate(0.5, 0.5)

        assert result is not None
        _, full, level, units, _, file_parts = result
        assert full == "Country"
        assert level == 0
        assert units == LocationService._get_adm0().entries
        assert file_parts == ["Country"]

    def test_locate_outside_any_boundary(self, warm_cache):
        assert LocationService.locate(50.0, 50.0) is None


@allure.feature("Location wireframe")
class TestWireframe:
    def test_creates_svg_and_projection(self, tmp_path):
        LocationService._folder = tmp_path / "maps"
        LocationService._folder.mkdir()

        focus_geometry = _square(0, 0, size=2.0)
        neighbour = _square(1.5, 1.5, size=2.0)
        focus = (focus_geometry, "Focus", "F")
        units = [(focus_geometry, "Focus", "F"), (neighbour, "Neighbour", "N")]

        file_name = LocationService.create_wireframe(1, units, focus, ["Country", "Region"])

        assert file_name == "Country_Region.svg"
        svg = (LocationService._folder / file_name).read_text(encoding="utf-8")
        assert '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">' in svg
        assert "<path d=" in svg
        assert 'fill="rgba(0, 0, 0, 0.12)"' in svg  # focus geometry highlighted

        projection = json.loads((LocationService._folder / "Country_Region.json").read_text(encoding="utf-8"))
        assert projection["width"] == 512
        assert projection["height"] == 512
        assert "zoom" in projection
        # Mercator center: lon is exact, lat is the inverse-projected y midpoint.
        assert projection["center"] == {"lat": pytest.approx(1.0, abs=1e-3), "lon": pytest.approx(1.0)}

        # Existing file short-circuits without regenerating.
        assert LocationService.create_wireframe(1, units, focus, ["Country", "Region"]) == file_name

    def test_returns_none_without_folder(self):
        LocationService._folder = None
        assert LocationService.create_wireframe(1, [], ("x", "x", "x"), ["A"]) is None


@allure.feature("Location download progress")
class TestDownloadProgress:
    def test_adm0_reports_per_country_progress(self, monkeypatch):
        seen: list[dict] = []

        def fake_fetch(url):
            progress = LocationService.get_download_progress()

            if progress is not None:
                seen.append(progress)

            if url.endswith("/ALL/ADM0"):
                return [
                    {"simplifiedGeometryGeoJSON": f"https://example.test/{i}.json", "boundaryName": f"Country{i}"}
                    for i in range(4)
                ]

            index = int(url.rsplit("/", 1)[1].split(".")[0])

            if index == 2:
                return None  # one failed download

            return {
                "features": [
                    {
                        "type": "Feature",
                        "geometry": mapping(_square(index * 2, 0)),
                        "properties": {"shapeISO": f"C{index}"},
                    }
                ]
            }

        monkeypatch.setattr(LocationService, "_fetch_json", staticmethod(fake_fetch))

        index = LocationService._get_adm0()

        assert len(index.entries) == 3
        assert LocationService.get_download_progress() is None
        # The metadata fetch happens before any progress is set; each country
        # fetch observes its own (position, failures so far, total).
        assert [(p["current"], p["failed"], p["total"]) for p in seen] == [(1, 0, 4), (2, 0, 4), (3, 0, 4), (4, 1, 4)]

    def test_adm_single_level_progress_and_clear(self, monkeypatch):
        seen: list[dict | None] = []

        def fake_fetch(url):
            seen.append(LocationService.get_download_progress())

            if url.endswith("/ADM1"):
                return {"simplifiedGeometryGeoJSON": "https://example.test/geo.json"}

            return {
                "features": [
                    {
                        "type": "Feature",
                        "geometry": mapping(_square(0, 0)),
                        "properties": {"shapeName": "Region", "shapeISO": "XX-01"},
                    }
                ]
            }

        monkeypatch.setattr(LocationService, "_fetch_json", staticmethod(fake_fetch))

        index = LocationService._load_adm("XX", 1)

        assert len(index.entries) == 1
        assert seen == [{"current": 0, "failed": 0, "total": 1}, {"current": 1, "failed": 0, "total": 1}]
        assert LocationService.get_download_progress() is None

    def test_progress_cleared_on_failure(self, monkeypatch):
        def fake_fetch(url):
            if url.endswith("/ALL/ADM0"):
                return [{"simplifiedGeometryGeoJSON": "https://example.test/0.json", "boundaryName": "X"}]

            raise RuntimeError("boom")

        monkeypatch.setattr(LocationService, "_fetch_json", staticmethod(fake_fetch))

        with pytest.raises(RuntimeError):
            LocationService._load_adm0()

        assert LocationService.get_download_progress() is None

    def test_cache_hit_reports_no_progress(self):
        LocationService._write_entries(
            LocationService._cache_folder / "xx_adm1.jsonl", [(_square(0, 0), "Region", "XX-01")]
        )

        index = LocationService._load_adm("XX", 1)

        assert len(index.entries) == 1
        assert LocationService.get_download_progress() is None
