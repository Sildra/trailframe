from datetime import timedelta

from sqlalchemy import select

from trailframe.models.activity import Activity, ActivitySummary, GarminActivity, GpxActivity
from trailframe.models.photo import Photo
from trailframe.services.activities.garmin_connect_service import GarminConnectService
from trailframe.services.core.configuration_service import ConfigurationService
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.core.thread_pool_service import ThreadPoolService
from trailframe.services.map.map_service import MapService
from trailframe.services.pipelines.executor import run_in_thread
from trailframe.services.service import Service


class ActivityService(Service):
    @classmethod
    async def list_activities(cls) -> list[ActivitySummary]:
        async with DatabaseService.create_session() as session:
            result = await session.execute(
                select(
                    Activity.id,
                    Activity.activity_id,
                    Activity.name,
                    Activity.activity_type,
                    Activity.start_time,
                    Activity.duration,
                    Activity.distance,
                ).order_by(Activity.start_time.desc())
            )

            summaries = [ActivitySummary(**row._mapping) for row in result.all()]

            if summaries:
                photo_dates = (await session.execute(select(Photo.date))).scalars().all()

                for summary in summaries:
                    if summary.start_time is None:
                        continue

                    start = summary.start_time - timedelta(minutes=10)
                    end = summary.start_time + timedelta(seconds=summary.duration or 0, minutes=10)

                    summary.photos = sum(
                        1 for photo_date in photo_dates if photo_date is not None and start <= photo_date <= end
                    )

            return summaries

    @classmethod
    async def get_activity(cls, activity_id: int) -> Activity | None:
        async with DatabaseService.create_session() as session:
            return await session.get(Activity, activity_id)

    @classmethod
    async def delete_activity(cls, activity_id: int) -> bool:
        async with DatabaseService.create_session() as session:
            activity = await session.get(Activity, activity_id)

            if activity is None:
                return False

            await session.delete(activity)
            await session.commit()

            return True

    @classmethod
    async def list_activity_photos(cls, activity_id: int) -> list[Photo]:
        async with DatabaseService.create_session() as session:
            activity = await session.get(Activity, activity_id)

            if activity is None or activity.start_time is None:
                return []

            start = activity.start_time - timedelta(minutes=10)
            end = activity.start_time + timedelta(seconds=activity.duration or 0, minutes=10)

            result = await session.execute(
                select(Photo).where(Photo.date >= start, Photo.date <= end).order_by(Photo.date)
            )

            return list(result.scalars().all())

    @classmethod
    async def sync_garmin(cls, email: str, password: str) -> bool:
        return await GarminConnectService.sync(email, password)

    @classmethod
    async def import_activity(cls, activity_id: int) -> Activity | None:
        async with DatabaseService.create_session() as session:
            garmin_activity = (
                await session.execute(select(GarminActivity).where(GarminActivity.activityId == activity_id))
            ).scalar_one_or_none()

            if garmin_activity is None:
                return None

            return await cls._save_activity(session, garmin_activity)

    @classmethod
    async def import_gpx(cls, gpx_id: int) -> Activity | None:
        async with DatabaseService.create_session() as session:
            gpx_activity = await session.get(GpxActivity, gpx_id)

            if gpx_activity is None:
                return None

            return await cls._save_activity(session, gpx_activity)

    @classmethod
    async def _save_activity(cls, session, source: GarminActivity | GpxActivity) -> Activity:
        activity = source.to_activity()

        existing = (
            await session.execute(select(Activity).where(Activity.activity_id == activity.activity_id))
        ).scalar_one_or_none()

        if existing is not None:
            existing.name = activity.name
            existing.activity_type = activity.activity_type
            existing.start_time = activity.start_time
            existing.duration = activity.duration
            existing.distance = activity.distance
            existing.trace = activity.trace
            activity = existing
        else:
            session.add(activity)

        await cls._link_photos(session, activity)

        await session.commit()
        await session.refresh(activity)

        await cls._create_maps(activity)

        session.add(activity)
        await session.commit()

        return activity

    @classmethod
    async def _create_maps(cls, activity: Activity) -> None:
        if not activity.activity_id:
            return

        bounds = cls._trace_bounds(activity.trace)

        if bounds is None:
            return

        try:
            projection = await run_in_thread(
                ThreadPoolService.get_executor(), cls._render_map, activity.activity_id, *bounds
            )
            points = await run_in_thread(
                ThreadPoolService.get_executor(), cls._render_trace, activity.activity_id, activity.trace, projection
            )
        except Exception as error:  # noqa: BLE001
            cls._log(f"map generation failed: {error}")
            return

        activity.map_data = {
            "map": projection,
            "trace": {
                "points": [list(point) for point in points],
                "start": list(points[0]) if points else None,
                "end": list(points[-1]) if points else None,
            },
        }

    @classmethod
    def _render_map(cls, activity_id: str, min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> dict:
        return MapService.create_map(activity_id, min_lat, min_lon, max_lat, max_lon)

    @classmethod
    def _render_trace(cls, activity_id: str, trace: list[dict], projection: dict) -> list[list[float]]:
        return MapService.create_trace(activity_id, trace, projection)

    @classmethod
    def _trace_bounds(cls, trace: list[dict]) -> tuple[float, float, float, float] | None:
        latitudes: list[float] = []
        longitudes: list[float] = []

        for point in trace:
            lat = point.get("lat")
            lon = point.get("lon")

            if lat is None or lon is None:
                continue

            try:
                latitudes.append(float(lat))
                longitudes.append(float(lon))
            except (TypeError, ValueError):
                continue

        if not latitudes:
            return None

        return (min(latitudes), min(longitudes), max(latitudes), max(longitudes))

    @classmethod
    async def _link_photos(cls, session, activity: Activity) -> None:
        if activity.start_time is None:
            return

        use_position = ConfigurationService.root().get_path_value(
            "scanners.Activity.use_activity_position", "Use Activity as GPS Position", False
        )

        start = activity.start_time - timedelta(minutes=10)
        end = activity.start_time + timedelta(seconds=activity.duration or 0, minutes=10)

        result = await session.execute(select(Photo).where(Photo.date >= start, Photo.date <= end))

        for photo in result.scalars().all():
            if use_position and photo.location_source is None and (photo.latitude is None or photo.longitude is None):
                position = Activity.interpolate_trace(activity.trace, photo.date, activity.start_time)

                if position is not None:
                    photo.latitude = position[0]
                    photo.longitude = position[1]
                    photo.location_source = "Activity"

            await session.merge(photo)
