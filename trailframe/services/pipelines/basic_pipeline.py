from typing import ClassVar

from trailframe.services.pipelines.item import Item
from trailframe.services.pipelines.pipeline import Pipeline
from trailframe.services.scanners.activity_scanner import ActivityScanner
from trailframe.services.scanners.database_scanner import DatabaseScanner
from trailframe.services.scanners.location_scanner import LocationScanner
from trailframe.services.scanners.object_scanner import ObjectScanner
from trailframe.services.scanners.perceptual_hash_scanner import PerceptualHashScanner
from trailframe.services.scanners.scanner import ForceFlag, Scanner


class BasicPipeline(Pipeline):
    _scanners: ClassVar[list[Scanner]] = [
        ActivityScanner(),
        LocationScanner(),
        ObjectScanner(),
        PerceptualHashScanner(),
        DatabaseScanner(),
    ]

    @classmethod
    def accepts(cls, item) -> bool:
        if isinstance(item, ForceFlag):
            return True

        if isinstance(item, Item):
            return any(scanner.accept(item) for scanner in cls._scanners)

        return super().accepts(item)
