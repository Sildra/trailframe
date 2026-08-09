import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import ClassVar

from garminconnect import Garmin
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gallery.models.activity import Activity, GarminActivity, GarminActivitySummary
from gallery.models.photo import Photo
from gallery.services.configuration_service import Node
from gallery.services.database_service import DatabaseService
from gallery.services.pipelines.executor import create_executor, run_in_thread
from gallery.services.service import Service


class GarminConnectService(Service):
    _tasks: ClassVar[set[asyncio.Task]] = set()
    _executor: ClassVar[ThreadPoolExecutor] = create_executor("garmin", 4)

    @classmethod
    async def sync(cls, email: str, password: str) -> bool:
        client = Garmin(email, password)

        try:
            (needs_mfa, _) = await run_in_thread(cls._executor, client.login)
        except Exception as error:
            cls._log(f"login failed: {error}")
            return False

        if needs_mfa:
            cls._log(f"login requires MFA: {needs_mfa}")
            return False

        task = asyncio.create_task(cls._sync(client))
        cls._tasks.add(task)
        task.add_done_callback(cls._tasks.discard)

        return True

    @classmethod
    async def _stop(cls) -> None:
        for task in list(cls._tasks):
            task.cancel()

        cls._tasks.clear()

    @classmethod
    async def _sync(cls, client: Garmin) -> None:
        try:
            existing_ids = await cls._existing_activity_ids()
            activities = await cls._fetch_activities(client, existing_ids)
            await cls._save(activities)
        except Exception as error:
            cls._log(f"import failed: {error}")

    @classmethod
    async def list_summaries(cls) -> list[GarminActivitySummary]:
        async with DatabaseService.create_session() as session:
            result = await session.execute(
                select(
                    GarminActivity.id,
                    GarminActivity.activityId,
                    GarminActivity.activityName,
                    GarminActivity.startTimeLocal,
                    GarminActivity.distance,
                    GarminActivity.duration,
                ).order_by(GarminActivity.startTimeLocal.desc())
            )

            imported_ids = {
                row[0]
                for row in (await session.execute(select(Activity.activity_id))).all()
                if row[0] is not None
            }

            summaries: list[GarminActivitySummary] = []

            for row in result.all():
                activity_id = f"Garmin:{row[1]}" if row[1] is not None else None

                summaries.append(
                    GarminActivitySummary(
                        id=row[0],
                        activityId=row[1],
                        activityName=row[2],
                        startTimeLocal=row[3],
                        distance=row[4],
                        duration=row[5],
                        photos=await cls._count_photos(session, row[3], row[5]),
                        imported=activity_id in imported_ids,
                    )
                )

            return summaries

    @classmethod
    async def _count_photos(cls, session: AsyncSession, start_time: datetime | None, duration: float | None) -> int:
        if start_time is None:
            return 0

        start = start_time - timedelta(minutes=10)
        end = start_time + timedelta(seconds=duration or 0, minutes=10)

        result = await session.execute(
            select(func.count()).select_from(Photo).where(Photo.date >= start, Photo.date <= end)
        )

        return result.scalar_one()

    @classmethod
    async def _fetch_activities(cls, client: Garmin, existing_ids: set[int]) -> list[GarminActivity]:
        activities: list[GarminActivity] = []
        start = 0
        limit = 10

        while True:
            batch = await run_in_thread(cls._executor, client.get_activities, start, limit)

            if not batch:
                break

            for data in batch:
                activity = GarminActivity.from_data(data)

                if activity is None or activity.activityId in existing_ids:
                    continue

                activities.append(activity)

            if len(batch) < limit:
                break

            start += limit

        for activity in activities:
            details = await run_in_thread(cls._executor, client.get_activity_details, str(activity.activityId))
            activity.jsonDetails = cls._filter_traces(details)

        return activities

    @classmethod
    def _filter_traces(cls, details: dict) -> dict:
        polyline_dto = details.get("geoPolylineDTO")

        if not isinstance(polyline_dto, dict):
            return details

        polyline = polyline_dto.get("polyline")

        if not isinstance(polyline, list):
            return details

        traces: list[dict] = []

        for point in polyline:
            if not isinstance(point, dict) or not point.get("valid"):
                continue

            trace: dict = {"lat": point.get("lat"), "lon": point.get("lon"), "time": point.get("time")}

            altitude = point.get("altitude")

            if altitude is not None:
                trace["altitude"] = altitude

            traces.append(trace)

        polyline_dto["polyline"] = traces

        return details

    @classmethod
    async def _existing_activity_ids(cls) -> set[int]:
        async with DatabaseService.create_session() as session:
            result = await session.execute(select(GarminActivity.activityId))

            return {row[0] for row in result.all() if row[0] is not None}

    @classmethod
    async def _save(cls, activities: list[GarminActivity]) -> list[GarminActivity]:
        saved: list[GarminActivity] = []

        async with DatabaseService.create_session() as session:
            for activity in activities:
                existing = (
                    await session.execute(
                        select(GarminActivity).where(GarminActivity.activityId == activity.activityId)
                    )
                ).scalar_one_or_none()

                if existing is not None:
                    continue

                session.add(activity)
                saved.append(activity)

            await session.commit()

        return saved
