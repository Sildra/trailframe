from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import allure
import pytest

from trailframe.models.photo import Photo
from trailframe.services.pipelines.executor import create_executor
from trailframe.services.pipelines.item import Item
from trailframe.services.scanners.database_scanner import DatabaseScanner
from trailframe.services.scanners.scanner import ForceFlag, Scanner, ScannerResult


class FakeScanner(Scanner):
    def __init__(self, name: str = "Fake", *, changed: bool = True):
        super().__init__(name)
        self.accept_result = True
        self.changed = changed
        self.fail = False
        self.calls: list = []

    def accept_(self, item) -> bool:
        return self.accept_result

    def executePhoto(self, item) -> bool:
        if self.fail:
            raise RuntimeError("boom")
        self.calls.append(item.photo)
        return self.changed


@pytest.fixture()
def executor() -> ThreadPoolExecutor:
    ex = create_executor("test-scanner", 2)
    yield ex
    ex.shutdown(wait=False, cancel_futures=True)


class TestScannerBase:
    @allure.title("Runs a synchronous scan on the executor and records timing")
    @pytest.mark.asyncio
    async def test_execute_runs_sync_scan(self, executor):
        scanner = FakeScanner()
        item = Item(Photo(path="x.jpg"))
        result = await scanner.execute(item, executor)
        assert result is ScannerResult.SUCCESS
        assert scanner.calls == [item.photo]
        assert scanner._run_count == 1
        assert scanner._run_total_ms >= 0

    @allure.title("Skips a disabled scanner and reports success")
    @pytest.mark.asyncio
    async def test_disabled_scanner_skips(self, executor):
        scanner = FakeScanner()
        scanner.enabled = False
        item = Item(Photo(path="x.jpg"))
        result = await scanner.execute(item, executor)
        assert result is ScannerResult.SUCCESS
        assert scanner.calls == []
        assert scanner._run_count == 0

    @allure.title("A disabled scanner is skipped even when forced")
    @pytest.mark.asyncio
    async def test_disabled_scanner_skips_even_when_forced(self, executor):
        scanner = FakeScanner()
        scanner.enabled = False
        scanner.accept(ForceFlag(["Fake"]))
        item = Item(Photo(path="x.jpg"))
        await scanner.execute(item, executor)
        assert scanner.calls == []

    @allure.title("Skips a scanner whose acceptance gate is false")
    @pytest.mark.asyncio
    async def test_not_accepted_is_skipped(self, executor):
        scanner = FakeScanner()
        scanner.accept_result = False
        item = Item(Photo(path="x.jpg"))
        await scanner.execute(item, executor)
        assert scanner.calls == []
        assert scanner._run_count == 0

    @allure.title("A forced scanner runs without the acceptance gate")
    @pytest.mark.asyncio
    async def test_forced_scanner_runs_without_gate(self, executor):
        scanner = FakeScanner()
        scanner.accept_result = False
        assert scanner.accept(ForceFlag(["Fake"])) is False
        assert scanner._forced is True
        item = Item(Photo(path="x.jpg"))
        await scanner.execute(item, executor)
        assert scanner.calls == [item.photo]

    @allure.title("A force flag un-sets scanners not in its list")
    def test_force_flag_unsets_others(self):
        scanner = FakeScanner()
        scanner.accept(ForceFlag(["Fake"]))
        assert scanner._forced is True
        scanner.accept(ForceFlag(["Other"]))
        assert scanner._forced is False

    @allure.title("Swallows scan exceptions, returns error, and does not record a run")
    @pytest.mark.asyncio
    async def test_failure_returns_error_and_not_recorded(self, executor, caplog):
        scanner = FakeScanner()
        scanner.fail = True
        item = Item(Photo(path="x.jpg"))
        result = await scanner.execute(item, executor)
        assert result is ScannerResult.ERROR
        assert scanner._run_count == 0
        assert any("failed" in record.getMessage() for record in caplog.records)

    @allure.title("Sets the updated flag only when the scan changed the photo")
    @pytest.mark.asyncio
    async def test_updated_only_when_changed(self, executor):
        scanner = FakeScanner(changed=False)
        item = Item(Photo(path="x.jpg"))
        await scanner.execute(item, executor)
        assert item.updated is False

        scanner2 = FakeScanner(changed=True)
        item2 = Item(Photo(path="x.jpg"))
        await scanner2.execute(item2, executor)
        assert item2.updated is True

    @allure.title("Leaves the scanner list unchanged for non-tracking scanners")
    @pytest.mark.asyncio
    async def test_non_tracking_does_not_append(self, executor):
        scanner = FakeScanner()
        item = Item(Photo(path="x.jpg"))
        await scanner.execute(item, executor)
        assert item.photo.scanners == []

    @allure.title("Reports aggregated run statistics")
    def test_run_stats(self):
        scanner = FakeScanner()
        assert scanner.get_run_stats() is None
        scanner._record(10.5)
        scanner._record(5.5)
        stats = scanner.get_run_stats()
        assert stats == {"scanner": "Fake", "count": 2, "total_ms": 16.0}

    @allure.title("Resets accumulated run statistics")
    def test_reset_run_stats(self):
        scanner = FakeScanner()
        scanner._record(1.0)
        scanner.reset_run_stats()
        assert scanner.get_run_stats() is None

    @allure.title("Accepts any photo by default")
    def test_accept_default_is_true(self):
        assert FakeScanner().accept(Item(Photo(path="x.jpg"))) is True

    @allure.title("A force flag is consumed by accept rather than scanned")
    def test_accept_force_flag_does_not_scan(self):
        scanner = FakeScanner()
        assert scanner.accept(ForceFlag(["Fake"])) is False
        assert scanner.calls == []


class TestAsyncScanner:
    @allure.title("Runs an async scan directly without the executor")
    @pytest.mark.asyncio
    async def test_execute_runs_async_scan_without_executor(self):
        calls = []

        class AsyncScanner(Scanner):
            async def executePhoto(self, item) -> bool:
                calls.append(item.photo)
                return True

        scanner = AsyncScanner("Async")
        item = Item(Photo(path="x.jpg"))
        result = await scanner.execute(item, None)
        assert result is ScannerResult.SUCCESS
        assert calls == [item.photo]
        assert scanner._run_count == 1


class TestDatabaseScanner:
    @allure.title("Accepts only updated items")
    def test_accepts_only_updated_items(self):
        scanner = DatabaseScanner()
        item = Item(Photo(path="x.jpg"))
        assert scanner.accept(item) is False
        item.updated = True
        assert scanner.accept(item) is True

    @allure.title("Writes the photo to the database and clears the updated flag")
    @pytest.mark.asyncio
    async def test_writes_and_clears_updated(self, db_session):
        from sqlalchemy import select

        from trailframe.models.photo import Photo

        scanner = DatabaseScanner()
        item = Item(Photo(path="x.jpg"))
        item.photo.filename = "x.jpg"
        item.updated = True

        result = await scanner.execute(item, None)
        assert result is ScannerResult.SUCCESS
        assert item.updated is False

        photo = (await db_session.execute(select(Photo).where(Photo.path == "x.jpg"))).scalar_one_or_none()
        assert photo is not None
        assert photo.filename == "x.jpg"
