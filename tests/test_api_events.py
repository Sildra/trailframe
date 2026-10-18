from __future__ import annotations

import allure
import pytest

from trailframe.api.events import _snapshot_message
from trailframe.services.map.location_service import LocationService
from trailframe.services.pipelines.pipeline_service import PipelineService


@pytest.fixture(autouse=True)
def stub_snapshot(monkeypatch):
    """Keep the stream composition test free of pipeline/service state."""
    monkeypatch.setattr(PipelineService, "get_snapshot", classmethod(lambda cls: {"Basic": "Idle"}))
    LocationService._download = None

    yield

    LocationService._download = None


@allure.feature("Events stream")
class TestSnapshotMessage:
    def test_no_download_no_boundaries_key(self):
        message, was_downloading = _snapshot_message(False)

        assert message == {"Basic": "Idle"}
        assert was_downloading is False

    def test_download_reports_progress_counts(self):
        LocationService._download = {"current": 3, "failed": 1, "total": 5}

        message, was_downloading = _snapshot_message(False)

        assert message["Boundaries"] == "(3/1/5)"
        assert message["Basic"] == "Idle"
        assert was_downloading is True

    def test_download_clears_with_empty_string_then_omits(self):
        message, was_downloading = _snapshot_message(True)

        assert message["Boundaries"] == ""
        assert was_downloading is False

        follow_up, was_downloading = _snapshot_message(was_downloading)

        assert "Boundaries" not in follow_up
        assert was_downloading is False

    def test_new_download_after_clear_reports_again(self):
        # Active download, then it finishes, then a new download starts.
        LocationService._download = {"current": 1, "failed": 0, "total": 2}
        message, was_downloading = _snapshot_message(False)
        assert message["Boundaries"] == "(1/0/2)"
        assert was_downloading is True

        LocationService._download = None
        message, was_downloading = _snapshot_message(was_downloading)
        assert message["Boundaries"] == ""

        LocationService._download = {"current": 1, "failed": 0, "total": 1}
        message, was_downloading = _snapshot_message(was_downloading)

        assert message["Boundaries"] == "(1/0/1)"
        assert was_downloading is True
