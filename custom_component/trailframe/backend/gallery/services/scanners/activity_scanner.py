from datetime import timedelta

from sqlalchemy import select

from gallery.models.activity import Activity
from gallery.models.photo import Photo
from gallery.services.configuration_service import Node
from gallery.services.database_service import DatabaseService
from gallery.services.scanners.scanner import Scanner


class ActivityScanner(Scanner):
    def __init__(self):
        super().__init__("Activity")
        self.use_activity_position = False

    def configure(self, config: Node) -> None:
        super().configure(config)
        self.use_activity_position = config.get_path_value(
            "scanners.Activity.use_activity_position", "Use Activity as GPS Position", False
        )

    def accept(self, photo: Photo) -> bool:
        return (
            self.use_activity_position
            and photo.date is not None
            and photo.location_source is None
            and (photo.latitude is None or photo.longitude is None)
        )

    async def scan(self, photo: Photo) -> None:
        if not self.use_activity_position or photo.date is None:
            return

        if photo.latitude is not None and photo.longitude is not None:
            return

        activity = await self._find_activity(photo)

        if activity is None:
            return

        position = Activity.interpolate_trace(activity.trace, photo.date, activity.start_time)

        if position is None:
            return

        photo.latitude = position[0]
        photo.longitude = position[1]
        photo.location_source = "Activity"

    async def _find_activity(self, photo: Photo) -> Activity | None:
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

        if not candidates:
            return None

        return min(candidates, key=lambda activity: abs(activity.start_time - photo.date))
