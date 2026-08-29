from datetime import timedelta
from typing import Any

from sqlalchemy import select

from trailframe.models.activity import Activity
from trailframe.services.core.configuration_service import Node
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.scanners.scanner import Scanner


class ActivityScanner(Scanner):
    def __init__(self):
        super().__init__("Activity")
        self.use_activity_position = False

    def configure_(self, config: Node) -> None:
        self.use_activity_position = config.get_path_value(
            "scanners.Activity.use_activity_position", "Use Activity as GPS Position", False
        )

    def accept_(self, item: Any) -> bool:
        photo = item.photo

        return (
            self.use_activity_position
            and photo.date is not None
            and photo.location_source is None
            and (photo.latitude is None or photo.longitude is None)
        )

    async def executePhoto(self, item) -> bool:
        photo = item.photo

        if not self.use_activity_position or photo.date is None:
            return False

        if photo.latitude is not None and photo.longitude is not None:
            return False

        activity = await self._find_activity(photo)

        if activity is None:
            return False

        position = Activity.interpolate_trace(activity.trace, photo.date, activity.start_time)

        if position is None:
            return False

        photo.latitude = position[0]
        photo.longitude = position[1]
        photo.location_source = "Activity"

        return True

    async def _find_activity(self, photo) -> Activity | None:
        start_upper = photo.date + timedelta(minutes=10)
        start_lower = photo.date - timedelta(hours=12)

        async with DatabaseService.create_session() as session:
            result = await session.execute(
                select(Activity).where(
                    Activity.start_time.is_not(None),
                    Activity.start_time >= start_lower,
                    Activity.start_time <= start_upper,
                )
            )

            candidates: list[Activity] = []

            for activity in result.scalars().all():
                end = activity.start_time + timedelta(seconds=activity.duration or 0, minutes=10)

                if photo.date <= end:
                    candidates.append(activity)

            return candidates

        candidates = await DatabaseService.execute(_query)

        if not candidates:
            return None

        return min(candidates, key=lambda activity: abs(activity.start_time - photo.date))
