import hashlib
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gallery.models.activity import Activity, GpxActivity, GpxActivitySummary
from gallery.models.photo import Photo
from gallery.services.database_service import DatabaseService
from gallery.services.service import Service


class GpxService(Service):
    @classmethod
    async def save(cls, content: str, filename: str) -> GpxActivity | None:
        activity = GpxActivity.from_gpx(content, filename)

        if activity is None:
            return None

        activity.content_hash = hashlib.sha1(content.encode("utf-8")).hexdigest()
        activity.filename = filename

        async with DatabaseService.create_session() as session:
            existing = (
                await session.execute(select(GpxActivity).where(GpxActivity.content_hash == activity.content_hash))
            ).scalar_one_or_none()

            if existing is not None:
                return existing

            session.add(activity)
            await session.commit()
            await session.refresh(activity)

        return activity

    @classmethod
    async def list_summaries(cls) -> list[GpxActivitySummary]:
        async with DatabaseService.create_session() as session:
            result = await session.execute(
                select(
                    GpxActivity.id,
                    GpxActivity.filename,
                    GpxActivity.name,
                    GpxActivity.activity_type,
                    GpxActivity.start_time,
                    GpxActivity.distance,
                    GpxActivity.duration,
                ).order_by(GpxActivity.start_time.desc())
            )

            imported_ids = {
                row[0]
                for row in (await session.execute(select(Activity.activity_id))).all()
                if row[0] is not None
            }

            summaries: list[GpxActivitySummary] = []

            for row in result.all():
                activity_id = f"GPX:{row[0]}" if row[0] is not None else None

                summaries.append(
                    GpxActivitySummary(
                        id=row[0],
                        filename=row[1],
                        name=row[2],
                        activity_type=row[3],
                        start_time=row[4],
                        distance=row[5],
                        duration=row[6],
                        photos=await cls._count_photos(session, row[4], row[6]),
                        imported=activity_id in imported_ids,
                    )
                )

            return summaries

    @classmethod
    async def _count_photos(cls, session: AsyncSession, start_time, duration: float | None) -> int:
        if start_time is None:
            return 0

        start = start_time - timedelta(minutes=10)
        end = start_time + timedelta(seconds=duration or 0, minutes=10)

        result = await session.execute(
            select(func.count()).select_from(Photo).where(Photo.date >= start, Photo.date <= end)
        )

        return result.scalar_one()
