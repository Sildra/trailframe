from trailframe.models.photo import Photo
from trailframe.services.configuration_service import Node
from trailframe.services.database_service import DatabaseService
from trailframe.services.pipelines.pipeline import ForcedScan, Pipeline
from trailframe.services.scanners.activity_scanner import ActivityScanner
from trailframe.services.scanners.brisque_scanner import BrisqueScanner
from trailframe.services.scanners.location_scanner import LocationScanner
from trailframe.services.scanners.object_scanner import ObjectScanner
from trailframe.services.scanners.perceptual_hash_scanner import PerceptualHashScanner


class BasicPipeline(Pipeline):
    _scanners = [ActivityScanner(), BrisqueScanner(), LocationScanner(), ObjectScanner(), PerceptualHashScanner()]
    _forced_scanners: list[str] | None = None

    @classmethod
    def _configure(cls, config: Node) -> None:
        for scanner in cls._scanners:
            scanner.configure(config)

    @classmethod
    def accepts(cls, item) -> bool:
        if isinstance(item, ForcedScan):
            return True

        if isinstance(item, Photo):
            return cls._forced_scanners is not None or any(scanner.accept(item) for scanner in cls._scanners)

        return super().accepts(item)

    @classmethod
    async def _process_item(cls, item) -> bool:
        if isinstance(item, ForcedScan):
            cls._forced_scanners = item.scanners or None
            cls._log(f"forced scan {'-> '.join(item.scanners) if item.scanners else 'off'}")
            return True

        executor = cls.get_executor()
        updated = False

        if cls._forced_scanners is not None:
            name_set = set(cls._forced_scanners)

            for scanner in cls._scanners:
                if scanner.name in name_set:
                    updated = True
                    await scanner.execute(item, executor, force=True)
        else:
            for scanner in cls._scanners:
                if scanner.accept(item):
                    updated = True
                    await scanner.execute(item, executor)

        if updated:
            async with DatabaseService.create_session() as session:
                await session.merge(item)
                await session.commit()

        return True
