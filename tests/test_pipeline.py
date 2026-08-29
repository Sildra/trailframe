from __future__ import annotations

import allure
import pytest

from trailframe.services.pipelines.pipeline import Pipeline, PipelineEmpty, is_pipeline_empty
from trailframe.services.pipelines.pipeline_service import PipelineService
from trailframe.services.scanners.scanner import ForceFlag


class TestPipelineEmpty:
    @allure.title("Detects the queue-drained sentinel, including the class itself")
    def test_is_pipeline_empty_detects_sentinel(self):
        assert is_pipeline_empty(PipelineEmpty()) is True
        assert is_pipeline_empty(PipelineEmpty) is True
        assert is_pipeline_empty("x") is False
        assert is_pipeline_empty(None) is False

    @allure.title("Accepts only the empty sentinel by default")
    def test_default_accepts(self):
        assert Pipeline.accepts(PipelineEmpty()) is True
        assert Pipeline.accepts("photo") is False


class TestPipelineQueue:
    @allure.title("Starts with an empty queue")
    def test_queue_starts_empty(self):
        assert Pipeline.get_queue_size() == 0

    @allure.title("Queues an item and reports its size")
    @pytest.mark.asyncio
    async def test_add_and_queue_size(self):
        await Pipeline.add("item")
        assert Pipeline.get_queue_size() == 1
        Pipeline._queue = None

    @allure.title("Drops the empty sentinel without queueing it")
    @pytest.mark.asyncio
    async def test_add_pipeline_empty_is_dropped(self):
        await Pipeline.add(PipelineEmpty())
        assert Pipeline.get_queue_size() == 0


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
