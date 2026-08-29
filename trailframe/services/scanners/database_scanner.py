from trailframe.services.core.database_service import DatabaseService
from trailframe.services.pipelines.item import Item
from trailframe.services.scanners.scanner import Scanner


class DatabaseScanner(Scanner):
    def __init__(self) -> None:
        super().__init__("Database")

    def accept(self, item) -> bool:
        return isinstance(item, Item) and item.updated

    async def executePhoto(self, item: Item) -> bool:
        if not item.updated:
            return False

        async with DatabaseService.create_session() as session:
            await session.merge(item.photo)
            await session.commit()

        item.updated = False

        return False
