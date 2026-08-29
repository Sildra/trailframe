from __future__ import annotations

import asyncio
import sys
from types import ModuleType
from unittest.mock import patch

import allure
from sqlalchemy import select

from trailframe.models.activity import GarminActivity
from trailframe.services.activities.garmin_connect_service import GarminConnectService
from trailframe.services.core.database_service import DatabaseService


def _activity_payload(activity_id: int, name: str) -> dict:
    return {
        "activityId": activity_id,
        "activityName": name,
        "startTimeLocal": "2023-06-01 08:30:00",
        "distance": 5000.0,
        "duration": 1800.0,
    }


def _details_payload() -> dict:
    return {
        "geoPolylineDTO": {
            "polyline": [
                {"time": 1000, "lat": 1.0, "lon": 1.0, "valid": True},
                {"time": 2000, "lat": 2.0, "lon": 2.0, "valid": True, "altitude": 123.0},
                {"time": 3000, "lat": 3.0, "lon": 3.0, "valid": False},
                {"lat": 4.0, "lon": 4.0, "valid": True},
            ]
        }
    }


class FakeGarmin:
    """Test double for garminconnect.Garmin: only the client surface the service uses."""

    def __init__(self, email=None, password=None, activities=(), details=None, **kwargs):
        self.email = email
        self.password = password
        self._activities = list(activities)
        self._details = details if details is not None else _details_payload()
        self.login_calls = 0
        self.activity_calls: list[tuple[int, int]] = []
        self.detail_calls: list[str] = []

    def login(self, tokenstore=None):
        self.login_calls += 1
        return None, None

    def get_activities(self, start=0, limit=20, activitytype=None):
        self.activity_calls.append((start, limit))
        return self._activities[start : start + limit]

    def get_activity_details(self, activity_id, maxchart=2000, maxpoly=4000):
        self.detail_calls.append(activity_id)
        return self._details


class _BrokenGarmin(FakeGarmin):
    def login(self, tokenstore=None):
        raise RuntimeError("invalid credentials")


def _installed_garmin_module(garmin) -> ModuleType:
    """Stand-in 'garminconnect' module so tests never need the real package installed.

    The service lazy-imports `from garminconnect import Garmin` inside `_sync`; putting
    this fake in sys.modules makes that import resolve to the provided class.
    """
    module = ModuleType("garminconnect")
    module.Garmin = garmin
    return module


class TestFilterTraces:
    @allure.title("Keeps valid points and adds altitude only when present")
    def test_filters_invalid_points(self):
        filtered = GarminConnectService._filter_traces(_details_payload())
        polyline = filtered["geoPolylineDTO"]["polyline"]

        assert len(polyline) == 3
        assert polyline[0] == {"time": 1000, "lat": 1.0, "lon": 1.0}
        assert polyline[1] == {"time": 2000, "lat": 2.0, "lon": 2.0, "altitude": 123.0}
        assert polyline[2] == {"time": None, "lat": 4.0, "lon": 4.0}

    @allure.title("Returns the payload untouched when there is no polyline to filter")
    def test_returns_payload_unchanged_when_no_polyline(self):
        payloads = [None, {}, {"geoPolylineDTO": {"polyline": "nope"}}]

        for payload in payloads:
            assert GarminConnectService._filter_traces(payload) is payload


class TestImportActivities:
    @allure.title("Imports new activities and returns the saved count")
    async def test_imports_new_activities(self, db_session):
        client = FakeGarmin(activities=[_activity_payload(1, "Morning Run"), _activity_payload(2, "Ride")])

        saved = await GarminConnectService._import_activities(client, set())

        assert saved == 2
        assert client.activity_calls == [(0, 10)]
        assert client.detail_calls == ["1", "2"]

        rows = (await db_session.execute(select(GarminActivity))).scalars().all()
        assert [row.activityId for row in rows] == [1, 2]

    @allure.title("Stores the filtered polyline in the activity details")
    async def test_stores_filtered_details(self, db_session):
        client = FakeGarmin(activities=[_activity_payload(1, "Run")])

        await GarminConnectService._import_activities(client, set())

        rows = (await db_session.execute(select(GarminActivity))).scalars().all()
        assert len(rows[0].jsonDetails["geoPolylineDTO"]["polyline"]) == 3

    @allure.title("Skips activities already known to the database")
    async def test_skips_already_known(self, db_session):
        client = FakeGarmin(activities=[_activity_payload(1, "Run"), _activity_payload(2, "Ride")])

        saved = await GarminConnectService._import_activities(client, {1})

        assert saved == 1
        assert client.detail_calls == ["2"]

    @allure.title("Skips payloads without an activity id")
    async def test_skips_payloads_without_id(self, db_session):
        client = FakeGarmin(activities=[{"activityName": "Broken"}, _activity_payload(2, "Ride")])

        saved = await GarminConnectService._import_activities(client, set())

        assert saved == 1
        assert client.detail_calls == ["2"]

    @allure.title("Paginates through batches until a short one appears")
    async def test_paginates(self, db_session):
        client = FakeGarmin(activities=[_activity_payload(index, f"Run {index}") for index in range(1, 13)])

        saved = await GarminConnectService._import_activities(client, set())

        assert saved == 12
        assert client.activity_calls == [(0, 10), (10, 10)]

    @allure.title("Reads existing activity ids from the database")
    async def test_existing_ids(self, db_session):
        async def _insert(session):
            session.add(GarminActivity(activityId=7, activityName="Run"))
            await session.commit()

        await DatabaseService.execute(_insert)

        assert await GarminConnectService._existing_activity_ids() == {7}


class TestSync:
    @allure.title("Syncs via the mocked Garmin client and persists the activities")
    async def test_sync_with_fake_client(self, db_session):
        created: list[FakeGarmin] = []

        def _factory(email, password):
            fake = FakeGarmin(email=email, password=password, activities=[_activity_payload(1, "Run"), _activity_payload(2, "Ride")])
            created.append(fake)
            return fake

        with patch.dict(sys.modules, {"garminconnect": _installed_garmin_module(_factory)}):
            result = await asyncio.to_thread(GarminConnectService._sync, "user@example.com", "s3cret")

        assert result is None
        assert created[0].email == "user@example.com"
        assert created[0].password == "s3cret"
        assert created[0].login_calls == 1

        rows = (await db_session.execute(select(GarminActivity))).scalars().all()
        assert len(rows) == 2

    @allure.title("Swallows and logs login failures")
    async def test_sync_swallows_login_errors(self, db_session):
        with patch.dict(sys.modules, {"garminconnect": _installed_garmin_module(_BrokenGarmin)}):
            result = await asyncio.to_thread(GarminConnectService._sync, "user@example.com", "s3cret")

        assert result is None

        rows = (await db_session.execute(select(GarminActivity))).scalars().all()
        assert rows == []