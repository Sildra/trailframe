from typing import ClassVar

from trailframe.services.pipelines.pipeline import Pipeline
from trailframe.services.scanners.activity_scanner import ActivityScanner
from trailframe.services.scanners.database_scanner import DatabaseScanner
from trailframe.services.scanners.location_scanner import LocationScanner
from trailframe.services.scanners.object_scanner import ObjectScanner
from trailframe.services.scanners.perceptual_hash_scanner import PerceptualHashScanner
from trailframe.services.scanners.scanner import Scanner


class BasicPipeline(Pipeline):
    _scanners: ClassVar[list[Scanner]] = [
        ActivityScanner(),
        LocationScanner(),
        ObjectScanner(),
        PerceptualHashScanner(),
        DatabaseScanner(),
    ]

