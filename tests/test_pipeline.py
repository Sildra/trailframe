from __future__ import annotations

import allure

from trailframe.services.pipelines.pipeline import Pipeline, PipelineEmpty
from trailframe.services.pipelines.pipeline_service import PipelineService
from trailframe.services.scanners import SCANNER_DEFINITIONS, create_scanner, get_scanner_definition
from trailframe.services.scanners.scanner import ForceFlag


class TestPipelineEmpty:
    @allure.title("Accepts only the empty sentinel by default")
    def test_default_accepts(self):
        pipeline = Pipeline("", [])
        assert pipeline.accepts(PipelineEmpty()) is True
        assert pipeline.accepts("photo") is False


class TestPipelineService:
    @allure.title("Registers the creation and basic pipelines on configure")
    def test_configure_registers_pipelines(self):
        from trailframe.services.core.configuration_service import Node

        PipelineService._configure(Node("root"))
        names = {p._name for p in PipelineService._pipelines}
        assert "CreationPipeline" in names
        assert "BasicPipeline" in names

    @allure.title("Routes force flags to the creation pipeline")
    def test_force_flag_marker_acceptance(self):
        assert PipelineService._pipelines[0].accepts(ForceFlag(["File"])) is True
        assert PipelineService._pipelines[0].accepts(ForceFlag()) is True


class TestScannerRegistry:
    @allure.title("Registers every concrete scanner with a definition")
    def test_registry_covers_all_scanners(self):
        names = {definition.name for definition in SCANNER_DEFINITIONS}
        assert names == {
            "File",
            "EXIF",
            "Thumbnail",
            "Activity",
            "Location",
            "Object",
            "PerceptualHash",
            "Rules",
            "Database",
        }

    @allure.title("Creates a scanner instance from the registry by name")
    def test_create_scanner(self):
        from trailframe.services.scanners.object_scanner import ObjectScanner

        scanner = create_scanner("Object")
        assert isinstance(scanner, ObjectScanner)
        assert create_scanner("Nope") is None

    @allure.title("Flags file and database scanners as non-remote")
    def test_file_and_database_are_not_remote(self):
        assert get_scanner_definition("File").can_be_remote is False
        assert get_scanner_definition("Database").can_be_remote is False

    @allure.title("Flags image-processing scanners as remote-capable")
    def test_remote_capable_scanners(self):
        remote = {definition.name for definition in SCANNER_DEFINITIONS if definition.can_be_remote}
        assert remote == {"EXIF", "Location", "Object", "PerceptualHash"}

    @allure.title("Exposes the can_be_remote flag on scanner instances")
    def test_instance_flags_match_registry(self):
        for definition in SCANNER_DEFINITIONS:
            scanner = definition.cls()
            assert scanner._can_be_remote == definition.can_be_remote
            assert scanner._can_be_disabled == definition.can_be_disabled
