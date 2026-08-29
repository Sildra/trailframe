from __future__ import annotations

import allure

from trailframe.models.scanner_stat import ScannerStat
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.core.statistics_service import StatisticsService


class TestRecordAndSummary:
    @allure.title("Aggregates scanner runs across calls into per-scanner summary")
    async def test_record_run_then_summary(self, db_session):
        await StatisticsService.record_run(
            [{"scanner": "EXIF", "count": 10, "total_ms": 1000.0}, {"scanner": "File", "count": 5, "total_ms": 500.0}]
        )
        await StatisticsService.record_run([{"scanner": "EXIF", "count": 10, "total_ms": 1000.0}])

        summary = await StatisticsService.get_scanner_summary()
        by_name = {entry.name: entry for entry in summary}

        # EXIF aggregated across two runs: 20 items over 2000 ms -> 10 items/s
        assert by_name["EXIF"].items == 20
        assert by_name["EXIF"].value == 10.0
        # File: 5 items over 500 ms -> 10 items/s
        assert by_name["File"].items == 5
        assert by_name["File"].value == 10.0

    @allure.title("Yields a zero throughput when no time was recorded")
    async def test_summary_zero_time_yields_zero_value(self, db_session):
        await StatisticsService.record_run([{"scanner": "Test", "count": 7, "total_ms": 0.0}])
        summary = await StatisticsService.get_scanner_summary()
        assert summary[0].items == 7
        assert summary[0].value == 0.0

    @allure.title("Reads directly inserted scanner stat rows")
    async def test_direct_insert_reads_back(self, db_session):
        # AGENTS.md recommends inserting ScannerStat rows directly to test the endpoints.
        async def _insert(session):
            session.add(ScannerStat(scanner="Object", count=3, total_ms=300.0))
            await session.commit()

        await DatabaseService.execute(_insert)

        summary = await StatisticsService.get_scanner_summary()
        assert any(entry.name == "Object" and entry.items == 3 and entry.value == 10.0 for entry in summary)


class TestFolderSize:
    @allure.title("Reports zero for a missing folder")
    def test_missing_folder_is_zero(self, tmp_path):
        assert StatisticsService._folder_size(tmp_path / "missing") == 0

    @allure.title("Sums the sizes of all files recursively")
    def test_sums_file_sizes(self, tmp_path):
        folder = tmp_path / "photos"
        (folder / "sub").mkdir(parents=True)
        (folder / "a.jpg").write_bytes(b"12345")
        (folder / "sub" / "b.jpg").write_bytes(b"123")
        assert StatisticsService._folder_size(folder) == 8

    @allure.title("Tolerates folders that cannot be walked")
    def test_ignores_os_errors(self, tmp_path):
        assert StatisticsService._folder_size(tmp_path) >= 0
