from sqlalchemy import select

from trailframe.models.photo import Photo
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.photos.duplicates_service import DuplicatesService
from trailframe.services.pipelines.item import Item
from trailframe.services.scanners.scanner import Scanner


class DatabaseScanner(Scanner):
    _can_be_disabled = False

    def __init__(self) -> None:
        super().__init__("Database")

    def accept(self, item) -> bool:
        return isinstance(item, Item) and item.updated

    async def executePhoto(self, item: Item) -> bool:
        if not item.updated:
            return False

        photo = item.photo
        phash_changed = item.phash_changed

        async def _save(session) -> None:
            result = await session.execute(select(Photo).where(Photo.path == photo.path))
            existing = result.scalar_one_or_none()

            if existing is None:
                session.add(photo)
            else:
                photo.id = existing.id
                await session.merge(photo)

            await session.commit()

            if phash_changed and photo.phash is not None and photo.id is not None:
                DuplicatesService.mark_added(photo.id, photo.phash)

        DatabaseService.execute_detached(_save)

        item.updated = False
        item.phash_changed = False

        return False
