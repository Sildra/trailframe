from __future__ import annotations

import allure

from trailframe.services.pipelines.pipeline import Pipeline, PipelineEmpty
from trailframe.services.pipelines.pipeline_service import PipelineService
from trailframe.services.scanners.scanner import ForceFlag


class TestPipelineEmpty:
    @allure.title("Accepts only the empty sentinel by default")
    def test_default_accepts(self):
        assert Pipeline.accepts(PipelineEmpty()) is True
        assert Pipeline.accepts("photo") is False


class TestPipelineService:
    @allure.title("Registers the creation and basic pipelines on configure")
    def test_configure_registers_pipelines(self):
        from trailframe.services.core.configuration_service import Node

        PipelineService._configure(Node("root"))
        names = {p.get_name() for p in PipelineService._pipelines}
        assert "CreationPipeline" in names
        assert "BasicPipeline" in names

    @allure.title("Routes force flags to the creation pipeline")
    def test_force_flag_marker_acceptance(self):
        from trailframe.services.pipelines.creation_pipeline import CreationPipeline

        assert CreationPipeline.accepts(ForceFlag(["File"])) is True
        assert CreationPipeline.accepts(ForceFlag()) is True
