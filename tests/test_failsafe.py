from __future__ import annotations

from pathlib import Path

import allure
import pytest

from trailframe.main import create_app
from trailframe.services.photos.folder_service import FolderService


def _args(config: Path, failsafe: bool):
    return type(
        "Args",
        (),
        {
            "config": config,
            "folder": config.parent / "data",
            "database": config.parent / "gallery.db",
            "port": None,
            "root_path": "/",
            "failsafe": failsafe,
            "openapi": None,
        },
    )()


class TestFailsafeFlag:
    @pytest.fixture(autouse=True)
    def _reset_failsafe(self):
        old = FolderService._failsafe
        FolderService._failsafe = False
        yield
        FolderService._failsafe = old

    @allure.title("The CLI failsafe flag applies for this run only")
    def test_cli_flag_does_not_reach_saved_config(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text("general:\n  failsafe: true\n", encoding="utf-8")

        create_app(_args(config, True))

        assert FolderService._failsafe is True
        assert "failsafe" not in config.read_text(encoding="utf-8")

    @allure.title("A stale failsafe value in the config no longer enables failsafe")
    def test_saved_flag_is_ignored_and_removed(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text("general:\n  failsafe: true\n", encoding="utf-8")

        create_app(_args(config, False))

        assert FolderService._failsafe is False
        assert "failsafe" not in config.read_text(encoding="utf-8")
