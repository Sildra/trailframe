from __future__ import annotations

import sqlite3

import allure

from trailframe.services.core.hardware_service import MIN_FREE_RAM_GB, detect_free_memory_gb, plan_detection
from trailframe.services.scanners import get_scanner_definitions


class TestHardwareDetection:
    @allure.title("Reads the free physical memory")
    def test_detects_memory(self):
        free_ram_gb = detect_free_memory_gb()
        assert free_ram_gb is None or free_ram_gb >= 0

    @allure.title("Disables heavy scanners on the first run when free memory is low")
    def test_first_run_disables_heavy_on_low_memory(self):
        record, disabled = plan_detection(MIN_FREE_RAM_GB - 0.5, ["Object"], None)

        assert disabled == ["Object"]
        assert record["low_memory"] is True
        assert record["heavy"] == ["Object"]
        assert record["auto_disabled"] == ["Object"]

    @allure.title("Keeps heavy scanners on the first run when free memory is sufficient")
    def test_first_run_keeps_heavy_on_enough_memory(self):
        record, disabled = plan_detection(MIN_FREE_RAM_GB + 1, ["Object"], None)

        assert disabled == []
        assert record["low_memory"] is False
        assert record["auto_disabled"] == []

    @allure.title("Treats an unknown memory size as sufficient")
    def test_unknown_memory_does_not_disable(self):
        record, disabled = plan_detection(None, ["Object"], None)

        assert disabled == []
        assert record["low_memory"] is False

    @allure.title("Evaluates a heavy scanner added after the first detection")
    def test_new_heavy_scanner_is_evaluated(self):
        previous, _ = plan_detection(MIN_FREE_RAM_GB - 0.5, ["Object"], None)
        record, disabled = plan_detection(MIN_FREE_RAM_GB - 0.5, ["Object", "Scenic"], previous)

        assert disabled == ["Scenic"]
        assert record["heavy"] == ["Object", "Scenic"]
        assert record["auto_disabled"] == ["Object", "Scenic"]

    @allure.title("Never disables a scanner that was already known")
    def test_known_scanner_is_not_disabled_again(self):
        previous, _ = plan_detection(MIN_FREE_RAM_GB - 0.5, ["Object"], None)
        record, disabled = plan_detection(MIN_FREE_RAM_GB - 0.5, ["Object"], previous)

        assert disabled == []
        assert record["auto_disabled"] == ["Object"]

    @allure.title("Marks the object scanner as heavy")
    def test_scanner_definitions_expose_heavy(self):
        heavy = {definition["name"] for definition in get_scanner_definitions() if definition["heavy"]}

        assert heavy == {"Object"}


class TestAppData:
    @allure.title("Reads a stored value directly from the database file")
    def test_reads_value(self, tmp_path):
        from trailframe.services.core.app_data import read_value

        path = tmp_path / "gallery.db"

        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE app_data (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
            connection.execute("INSERT INTO app_data VALUES ('hardware_detection', '{\"free_ram_gb\": 4.0}', '')")

        assert read_value(path, "hardware_detection") == '{"free_ram_gb": 4.0}'
        assert read_value(path, "missing") is None
        assert read_value(tmp_path / "missing.db", "hardware_detection") is None
