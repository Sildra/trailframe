from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, ClassVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trailframe.models.activity import Activity, GarminActivity, GarminActivitySummary
from trailframe.models.photo import Photo
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.core.thread_pool_service import ThreadPoolService
from trailframe.services.service import Service

if TYPE_CHECKING:
    from garminconnect import Garmin


class GarminConnectService(Service):
    _tasks: ClassVar[set[asyncio.Task]] = set()

    @classmethod
    async def sync(cls, email: str, password: str) -> bool:
        task = asyncio.create_task(ThreadPoolService.run(cls._sync, email, password))
        cls._tasks.add(task)
        task.add_done_callback(cls._tasks.discard)

        return True

    @classmethod
    async def _stop(cls) -> None:
        for task in list(cls._tasks):
            task.cancel()

        cls._tasks.clear()

    @classmethod
    def _sync(cls, email: str, password: str) -> None:
        try:
            from garminconnect import Garmin

            client = Garmin(email, password)
            client.login()
            asyncio.run(cls._import(client))
        except Exception as error:  # noqa: BLE001
            cls._log(f"sync failed: {error}")

    @classmethod
    async def _import(cls, client: Garmin) -> None:
        existing_ids = await cls._existing_activity_ids()
        cls._log(f"importing activities (already have {len(existing_ids)})...")
        count = await cls._import_activities(client, existing_ids)
        cls._log(f"import done: {count} new activity(ies) saved")

    @classmethod
    async def _import_activities(cls, client: Garmin, existing_ids: set[int]) -> int:
        saved = 0
        start = 0
        limit = 10
        fetched = 0
        skipped = 0

        while True:
            cls._log(f"fetching activities {start}-{start + limit}...")
            batch = client.get_activities(start, limit)

            if not batch:
                break

            fetched += len(batch)

            for data in batch:
                activity = GarminActivity.from_data(data)

                if activity is None or activity.activityId in existing_ids:
                    skipped += 1
                    continue

                cls._log(f"fetching details for activity {activity.activityId} ({activity.activityName})...")
                details = client.get_activity_details(str(activity.activityId))
                activity.jsonDetails = cls._filter_traces(details)

                if await cls._save_activity(activity):
                    saved += 1
                    existing_ids.add(activity.activityId)

            if len(batch) < limit:
                break

            start += limit

        cls._log(f"done importing activities: {fetched} fetched, {saved} new, {skipped} already known")

        return saved

    @classmethod
    async def _save_activity(cls, activity: GarminActivity) -> bool:
        async def _save(session) -> bool:
            existing = (
                await session.execute(select(GarminActivity).where(GarminActivity.activityId == activity.activityId))
            ).scalar_one_or_none()

            if existing is not None:
                return False

            session.add(activity)
            await session.commit()

            return True

        return await DatabaseService.execute(_save)

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
    def _filter_traces(cls, details: dict) -> dict:
        if not isinstance(details, dict):
            return details

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
