import asyncio
from datetime import datetime, timedelta
from typing import ClassVar

from garminconnect import Garmin
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trailframe.models.activity import Activity, GarminActivity, GarminActivitySummary
from trailframe.models.photo import Photo
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.core.thread_pool_service import ThreadPoolService
from trailframe.services.pipelines.executor import run_in_thread
from trailframe.services.service import Service


class GarminConnectService(Service):
    _tasks: ClassVar[set[asyncio.Task]] = set()

    @classmethod
    async def sync(cls, email: str, password: str) -> bool:
        client = Garmin(email, password)

        try:
            (needs_mfa, _) = await run_in_thread(ThreadPoolService.get_executor(), client.login)
        except Exception as error:  # noqa: BLE001
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
            cls._log(f"importing activities (already have {len(existing_ids)})...")
            activities = await cls._fetch_activities(client, existing_ids)
            saved = await cls._save(activities)
            cls._log(f"import done: {len(saved)} new activity(ies) saved")
        except Exception as error:  # noqa: BLE001
            cls._log(f"import failed: {error}")

    @classmethod
    async def list_summaries(cls) -> list[GarminActivitySummary]:
        async def _summaries(session) -> list[GarminActivitySummary]:
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
                row[0] for row in (await session.execute(select(Activity.activity_id))).all() if row[0] is not None
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

        return await DatabaseService.execute(_summaries)

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
        fetched = 0
        skipped = 0

        while True:
            cls._log(f"fetching activities {start}-{start + limit}...")
            batch = await run_in_thread(ThreadPoolService.get_executor(), client.get_activities, start, limit)

            if not batch:
                break

            fetched += len(batch)

            for data in batch:
                activity = GarminActivity.from_data(data)

                if activity is None or activity.activityId in existing_ids:
                    skipped += 1
                    continue

                activities.append(activity)

            if len(batch) < limit:
                break

            start += limit

        cls._log(f"done fetching activities: {fetched} fetched, {len(activities)} new, {skipped} already known")

        for activity in activities:
            cls._log(f"fetching details for activity {activity.activityId} ({activity.activityName})...")
            details = await run_in_thread(
                ThreadPoolService.get_executor(), client.get_activity_details, str(activity.activityId)
            )
            activity.jsonDetails = cls._filter_traces(details)

        cls._log(f"done fetching details for {len(activities)} activities")

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
        async def _query(session) -> set[int]:
            result = await session.execute(select(GarminActivity.activityId))
            return {row[0] for row in result.all() if row[0] is not None}

        return await DatabaseService.execute(_query)

    @classmethod
    async def _save(cls, activities: list[GarminActivity]) -> list[GarminActivity]:
        async def _save_all(session) -> list[GarminActivity]:
            saved: list[GarminActivity] = []

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

        return await DatabaseService.execute(_save_all)
