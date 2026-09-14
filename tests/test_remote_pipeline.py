from __future__ import annotations

import allure
import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from trailframe.main import create_app
from trailframe.models.photo import Photo
from trailframe.services.core.configuration_service import Node
from trailframe.services.pipelines.pipeline_service import PipelineService
from trailframe.services.scanners.remote_scanner import RemoteScanner
from trailframe.services.scanners.scanner import ScannerResult
from trailframe.services.service import ServiceState


class TestPipelineConfig:
    @allure.title("Builds default pipelines from an empty config")
    def test_default_pipelines(self):
        config = Node("root")

        PipelineService._configure(config)

        assert [pipeline._name for pipeline in PipelineService._pipelines] == ["CreationPipeline", "BasicPipeline"]
        assert [scanner.name for scanner in PipelineService._pipelines[0]._scanners] == [
            "File",
            "EXIF",
            "Thumbnail",
            "Database",
        ]
        assert [scanner.name for scanner in PipelineService._pipelines[1]._scanners] == [
            "Activity",
            "Location",
            "Object",
            "PerceptualHash",
            "Database",
        ]
        assert PipelineService.get_remote_pipelines() == []

    @allure.title("Falls back to defaults when the pipelines list is empty")
    def test_empty_pipelines_uses_defaults(self):
        config = Node("root")
        config.get_node("pipelines").set_value([])

        PipelineService._configure(config)

        assert [pipeline._name for pipeline in PipelineService._pipelines] == ["CreationPipeline", "BasicPipeline"]

    @allure.title("Builds pipelines from the documented YAML pipelines list")
    def test_yaml_pipelines_list(self, tmp_path):
        from trailframe.services.core.configuration_service import ConfigurationService

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "pipelines:\n"
            " - Basic:\n"
            "    remote: false\n"
            "    scanners:\n"
            "     - EXIF\n"
            " - RemoteDeep:\n"
            "    remote: localhost:8000\n"
            "    scanners:\n"
            "     - Object\n"
            "     - Location\n",
            encoding="utf-8",
        )

        ConfigurationService.configure(config_file)
        ConfigurationService.load()

        PipelineService._configure(ConfigurationService.root())

        assert [pipeline._name for pipeline in PipelineService._pipelines] == ["Basic", "RemoteDeep"]

        entry = PipelineService.get_remote_pipeline("RemoteDeep")
        assert entry == {"name": "RemoteDeep", "remote": "http://localhost:8000", "scanners": ["Object", "Location"]}

    @allure.title("Builds a local pipeline from the pipelines config")
    def test_local_pipeline(self):
        config = Node("root")
        config.get_node("pipelines").set_value([{"Basic": {"remote": "", "scanners": ["Object"]}}])

        PipelineService._configure(config)

        pipelines = PipelineService._pipelines
        assert len(pipelines) == 1
        assert pipelines[0]._name == "Basic"
        assert [scanner.name for scanner in pipelines[0]._scanners] == ["File", "Object", "Database"]

    @allure.title("Injects the File scanner into the first pipeline")
    def test_file_injected_first(self):
        config = Node("root")
        config.get_node("pipelines").set_value([{"Local": {"remote": "", "scanners": ["EXIF"]}}])

        PipelineService._configure(config)

        assert [scanner.name for scanner in PipelineService._pipelines[0]._scanners] == ["File", "EXIF", "Database"]

    @allure.title("Does not inject the File scanner into later pipelines")
    def test_file_only_first(self):
        config = Node("root")
        config.get_node("pipelines").set_value(
            [{"First": {"remote": "", "scanners": ["EXIF"]}}, {"Second": {"remote": "", "scanners": ["Object"]}}]
        )

        PipelineService._configure(config)

        assert [scanner.name for scanner in PipelineService._pipelines[0]._scanners] == ["File", "EXIF", "Database"]
        assert [scanner.name for scanner in PipelineService._pipelines[1]._scanners] == ["Object", "Database"]

    @allure.title("Ignores internal scanners listed in the config")
    def test_ignores_internal_scanners(self):
        config = Node("root")
        config.get_node("pipelines").set_value([{"Local": {"remote": "", "scanners": ["File", "Database", "EXIF"]}}])

        PipelineService._configure(config)

        assert [scanner.name for scanner in PipelineService._pipelines[0]._scanners] == ["File", "EXIF", "Database"]

    @allure.title("Builds a remote pipeline with a RemoteScanner delegating listed scanners")
    def test_remote_pipeline(self):
        config = Node("root")
        config.get_node("pipelines").set_value(
            [{"Remote": {"remote": "localhost:8000", "scanners": ["Object", "EXIF"]}}]
        )

        PipelineService._configure(config)

        pipelines = PipelineService._pipelines
        assert len(pipelines) == 1
        assert [scanner.name for scanner in pipelines[0]._scanners] == ["Remote", "Database"]

        entry = PipelineService.get_remote_pipeline("Remote")
        assert entry == {"name": "Remote", "remote": "http://localhost:8000", "scanners": ["Object", "EXIF"]}

    @allure.title("Builds multiple pipelines from a list")
    def test_multiple_pipelines(self):
        config = Node("root")
        config.get_node("pipelines").set_value(
            [
                {"Basic": {"remote": "", "scanners": ["Object"]}},
                {"RemoteDeep": {"remote": "host:9000", "scanners": ["EXIF", "Location", "PerceptualHash"]}},
            ]
        )

        PipelineService._configure(config)

        pipelines = PipelineService._pipelines
        assert [pipeline._name for pipeline in pipelines] == ["Basic", "RemoteDeep"]

        entries = PipelineService.get_remote_pipelines()
        assert len(entries) == 1
        assert entries[0]["name"] == "RemoteDeep"
        assert entries[0]["remote"] == "http://host:9000"
        assert entries[0]["scanners"] == ["EXIF", "Location", "PerceptualHash"]


class TestScannerDefinitionsApi:
    @allure.title("Lists only disabled-capable scanner names")
    def test_list_scanners(self, app):
        response = app.get("/api/pipeline/scanners")
        assert response.status_code == 200

        values = response.json()
        assert values == sorted(values)
        assert "File" not in values
        assert "Database" not in values
        assert "Remote" not in values


class TestRemoteScanner:
    @allure.title("Filters File and Database out of delegated scanners")
    def test_filters_internal_scanners(self):
        scanner = RemoteScanner("localhost:8000", ["Object", "File", "Database"])

        assert scanner._scanner_names == ["Object"]

    @allure.title("Normalizes remote targets to URLs")
    def test_normalize_remote(self):
        assert RemoteScanner("localhost:8000", [])._remote == "http://localhost:8000"
        assert RemoteScanner("http://x:8000", [])._remote == "http://x:8000"
        assert RemoteScanner("", [])._remote == ""

    @allure.title("Accepts locally when any delegated scanner accepts the photo")
    def test_accept_local_gating(self):
        scanner = RemoteScanner("localhost:8000", ["Object"])

        photo = Photo(path="/tmp/a.jpg")
        assert scanner.accept(photo) is True

        photo.scanners = ["Object"]
        assert scanner.accept(photo) is False

    @allure.title("Accepts locally using the same gating as the delegated scanners")
    def test_accept_delegates_gating(self):
        scanner = RemoteScanner("localhost:8000", ["EXIF", "PerceptualHash"])

        photo = Photo(path="/tmp/a.jpg")
        assert scanner.accept(photo) is True

        photo.exif = {"ImageWidth": 1}
        assert scanner.accept(photo) is True

        photo.phash = bytes.fromhex("00" * 8)
        assert scanner.accept(photo) is False

    @allure.title("Applies remote results to the photo")
    @pytest.mark.asyncio
    async def test_execute_photo_applies_results(self, monkeypatch: MonkeyPatch, tmp_path):
        source = tmp_path / "photo.jpg"
        source.write_bytes(b"data")

        from trailframe.services.pipelines.item import Item

        async def fake_run(_, url: str, path, scanner_names) -> dict:
            assert path == source
            assert scanner_names == ["Object", "EXIF", "PerceptualHash"]
            assert url.endswith("/api/pipeline/remote-scan")

            return {
                "filename": source.name,
                "file_size": 4,
                "date": "2024-05-06T12:34:56",
                "exif": {"ImageWidth": 1},
                "objects": [{"label": "person", "confidence": 0.9, "box": [1, 2, 3, 4]}],
                "scanners": ["Object", "EXIF", "PerceptualHash"],
                "phash": "0102",
            }

        monkeypatch.setattr("trailframe.services.scanners.remote_scanner.ThreadPoolService.run", fake_run)

        scanner = RemoteScanner("localhost:8000", ["Object", "EXIF", "PerceptualHash"])
        photo = Photo(path=str(source), source="File")
        item = Item(photo)

        result = await scanner.execute(item)

        assert result is ScannerResult.SUCCESS
        assert item.updated is True
        assert photo.exif == {"ImageWidth": 1}
        assert photo.objects == [{"label": "person", "confidence": 0.9, "box": [1, 2, 3, 4]}]
        assert photo.phash == bytes.fromhex("0102")
        assert item.phash_changed is True
        assert photo.scanners == ["EXIF", "Object", "PerceptualHash"]

    @allure.title("Skips execution without a remote target or scanners")
    @pytest.mark.asyncio
    async def test_execute_photo_skips_incomplete(self, tmp_path):
        source = tmp_path / "photo.jpg"
        source.write_bytes(b"data")

        from trailframe.services.pipelines.item import Item

        scanner = RemoteScanner("", [])
        item = Item(Photo(path=str(source)))

        assert await scanner.executePhoto(item) is False


class TestRemotePipelineApi:
    @allure.title("Lists configured remote pipelines")
    def test_list_remote_pipelines(self, app):
        PipelineService._configure(Node("root"))

        response = app.get("/api/pipeline/remote")
        assert response.status_code == 200
        assert response.json() == []

    @allure.title("Reports which pipelines were kept, added and removed on save")
    def test_apply_summary(self, app):
        response = app.post(
            "/api/configuration",
            json={
                "children": {
                    "pipelines": {
                        "value": [
                            {"Keep": {"remote": "", "scanners": ["Object"]}},
                            {"New": {"remote": "", "scanners": ["EXIF"]}},
                        ]
                    }
                }
            },
        )

        assert response.status_code == 200
        applied = response.json()["applied"]
        assert applied["added"] == ["Keep", "New"]
        assert applied["kept"] == []
        assert applied["migrated"] == []
        assert set(applied["removed"]) == {"CreationPipeline", "BasicPipeline"}

    @allure.title("Returns 404 for an unknown remote pipeline")
    def test_get_unknown_pipeline(self, app):
        response = app.get("/api/pipeline/remote/nope")
        assert response.status_code == 404

    @allure.title("Returns 404 pushing to an unknown pipeline")
    def test_push_unknown_pipeline(self, app):
        response = app.post("/api/pipeline/remote/nope/push", files={"file": ("a.jpg", b"data", "image/jpeg")})
        assert response.status_code == 404

    @allure.title("Determines status is unreachable for a dead remote")
    def test_status_unreachable(self, tmp_path):
        (tmp_path / "config.yaml").write_text(
            "pipelines:\n- Dead:\n    remote: localhost:1\n    scanners:\n    - Object\n", encoding="utf-8"
        )

        args = type(
            "Args",
            (),
            {
                "config": tmp_path / "config.yaml",
                "folder": tmp_path / "data",
                "database": tmp_path / "gallery.db",
                "port": None,
                "root_path": "/",
                "failsafe": True,
                "openapi": None,
            },
        )()

        with TestClient(create_app(args)) as client:
            response = client.get("/api/pipeline/remote/Dead/status")

        assert response.status_code == 200
        assert response.json()["status"] == "unreachable"


class TestPipelineLiveReconfigure:
    @allure.title("Reconfigures the scanners of running pipelines in place")
    def test_reconfigures_live_scanners_in_place(self):
        config = Node("root")
        config.get_node("pipelines").set_value([{"Basic": {"remote": "", "scanners": ["Activity", "Object"]}}])

        PipelineService._configure(config)
        pipeline = PipelineService._pipelines[0]
        object_scanner = next(scanner for scanner in pipeline._scanners if scanner.name == "Object")
        assert object_scanner._enabled is True

        PipelineService._state = ServiceState.STARTED
        try:
            updated = Node("root")
            updated.get_node("scanners.Object.enabled").set_value(False)
            PipelineService._configure(updated)
        finally:
            PipelineService._state = ServiceState.NOT_STARTED

        assert PipelineService._pipelines == [pipeline]
        assert object_scanner._enabled is False

    @allure.title("Migrates pipeline structure changes live, keeping unchanged pipelines untouched")
    async def test_migrates_structure_changes_live(self, db_session):
        config = Node("root")
        config.get_node("pipelines").set_value([{"Basic": {"remote": "", "scanners": ["Object"]}}])

        PipelineService._configure(config)
        basic = PipelineService._pipelines[0]

        await PipelineService.start()
        try:
            updated = Node("root")
            updated.get_node("pipelines").set_value(
                [{"Basic": {"remote": "", "scanners": ["Object"]}}, {"Extra": {"remote": "", "scanners": ["EXIF"]}}]
            )
            PipelineService._configure(updated)

            assert PipelineService._pipelines[0] is basic
            assert [pipeline._name for pipeline in PipelineService._pipelines] == ["Basic", "Extra"]
            assert PipelineService.get_last_reconfigure() == {
                "kept": ["Basic"],
                "migrated": [],
                "added": ["Extra"],
                "removed": [],
            }
        finally:
            await PipelineService.stop()

    @allure.title("Keeps running instances when pipelines are only reordered")
    async def test_keeps_instances_on_reorder_without_restart(self, db_session):
        config = Node("root")
        config.get_node("pipelines").set_value(
            [
                {"A": {"remote": "localhost:2", "scanners": ["Object"]}},
                {"B": {"remote": "localhost:3", "scanners": ["EXIF"]}},
            ]
        )
        PipelineService._configure(config)
        a, b = PipelineService._pipelines

        await PipelineService.start()
        try:
            updated = Node("root")
            updated.get_node("pipelines").set_value(
                [
                    {"B": {"remote": "localhost:3", "scanners": ["EXIF"]}},
                    {"A": {"remote": "localhost:2", "scanners": ["Object"]}},
                ]
            )
            PipelineService._configure(updated)

            assert PipelineService._pipelines == [b, a]
        finally:
            await PipelineService.stop()

    @allure.title("Migrates a pipeline whose position changes the injected scanners")
    async def test_migrates_when_position_injects_file_scanner(self, db_session):
        config = Node("root")
        config.get_node("pipelines").set_value(
            [{"A": {"remote": "", "scanners": ["EXIF"]}}, {"B": {"remote": "", "scanners": ["Object"]}}]
        )
        PipelineService._configure(config)
        a, b = PipelineService._pipelines

        await PipelineService.start()
        try:
            updated = Node("root")
            updated.get_node("pipelines").set_value(
                [{"B": {"remote": "", "scanners": ["Object"]}}, {"A": {"remote": "", "scanners": ["EXIF"]}}]
            )
            PipelineService._configure(updated)

            front, back = PipelineService._pipelines
            assert front is not b
            assert back is not a
            assert [scanner.name for scanner in front._scanners] == ["File", "Object", "Database"]
        finally:
            await PipelineService.stop()

    @allure.title("Carries items still queued into a replacement pipeline")
    def test_carries_pending_items_into_replacement(self):
        config = Node("root")
        config.get_node("pipelines").set_value([{"Basic": {"remote": "", "scanners": ["Object"]}}])

        PipelineService._configure(config)
        basic = PipelineService._pipelines[0]
        basic.add("queued-photo")

        PipelineService._state = ServiceState.STARTED
        try:
            updated = Node("root")
            updated.get_node("pipelines").set_value([{"Basic": {"remote": "", "scanners": ["EXIF"]}}])
            PipelineService._configure(updated)

            replacement = PipelineService._pipelines[0]
            assert replacement is not basic
            assert replacement.take_pending() == ["queued-photo"]
        finally:
            for pipeline in PipelineService._pipelines:
                pipeline.stop()
            PipelineService._state = ServiceState.NOT_STARTED

    @allure.title("Collects only items still queued after a stop")
    def test_take_pending_collects_remaining_items(self):
        config = Node("root")
        config.get_node("pipelines").set_value([{"Basic": {"remote": "", "scanners": ["Object"]}}])

        PipelineService._configure(config)
        basic = PipelineService._pipelines[0]
        basic.add("alpha")
        basic.add("beta")

        assert basic.take_pending() == ["alpha", "beta"]
        assert basic.take_pending() == []

    @allure.title("Routes items onwards when a pipeline vanished during handoff")
    async def test_next_handles_pipeline_removed_from_list(self):
        config = Node("root")
        config.get_node("pipelines").set_value(
            [{"A": {"remote": "", "scanners": ["Object"]}}, {"B": {"remote": "", "scanners": ["EXIF"]}}]
        )
        PipelineService._configure(config)
        a, b = PipelineService._pipelines

        previous = PipelineService._pipelines
        PipelineService._pipelines = [b]
        try:
            photo = Photo(path="unused.jpg", filename="unused.jpg", file_size=0)
            await PipelineService.next(photo, a)
        finally:
            PipelineService._pipelines = previous

        pending = b.take_pending()
        assert len(pending) == 1
        assert pending[0] is photo
