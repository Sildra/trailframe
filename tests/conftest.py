from __future__ import annotations

import re
from pathlib import Path

import allure
import pytest
from fastapi.testclient import TestClient

from trailframe.main import create_app

_WORD_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item):
    """Group Allure results by the enclosing test class (feature) and tag the
    test method with a human-readable story label, so individual tests don't
    need to repeat feature/story decorators."""
    if isinstance(item, pytest.Function):
        cls = item.getparent(pytest.Class)
        if cls is not None:
            allure.dynamic.feature(_humanize(cls.name))
        allure.dynamic.story(_humanize(item.name))
    yield


def _humanize(name: str) -> str:
    return _WORD_BOUNDARY.sub(" ", name).replace("_", " ").strip()


def _build_args(tmp_path: Path):
    return type(
        "Args",
        (),
        {
            "config": tmp_path / "config.yaml",
            "folder": tmp_path / "data",
            "database": tmp_path / "gallery.db",
            "port": None,
            "root_path": "/",
            "failsafe": False,
            "openapi": None,
        },
    )()


class AppHarness:
    """Thin wrapper exposing the TestClient plus a way to run DB work on the
    app's own event-loop thread (where DatabaseService sessions must be created).
    """

    def __init__(self, client: TestClient):
        self.client = client

    def __getattr__(self, name):
        return getattr(self.client, name)

    def db(self, func):
        import inspect

        if inspect.iscoroutine(func):
            return self.client.portal.call(lambda: func)
        return self.client.portal.call(func)


@pytest.fixture()
def app(tmp_path) -> AppHarness:
    instance = create_app(_build_args(tmp_path))

    with TestClient(instance) as client:
        yield AppHarness(client)

    from trailframe.services.core.configuration_service import ConfigurationService
    from trailframe.services.map.location_service import LocationService
    from trailframe.services.photos.folder_service import FolderService
    from trailframe.services.photos.thumbnail_service import ThumbnailService

    FolderService._folder = None
    FolderService._trash_folder = None
    LocationService._folder = None
    LocationService._cache_folder = None
    ThumbnailService._folder = None
    ThumbnailService._sizes = []
    ConfigurationService._root = type("Root", (), {"to_dict": lambda self: {}})()


@pytest.fixture()
async def db_session(tmp_path):
    """Configure and start a standalone DatabaseService against a temp file."""
    from trailframe.services.core.configuration_service import Node
    from trailframe.services.core.database_service import DatabaseService

    config = Node("general")
    config.get_node("database").set_value(str(tmp_path / "test.db"))

    DatabaseService.configure(config)
    await DatabaseService.start()

    async with DatabaseService.create_session() as session:
        yield session

    await DatabaseService.stop()
