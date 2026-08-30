from typing import ClassVar

from trailframe.services.pipelines.item import Item
from trailframe.services.pipelines.pipeline import Pipeline
from trailframe.services.scanners.database_scanner import DatabaseScanner
from trailframe.services.scanners.exif_scanner import ExifScanner
from trailframe.services.scanners.file_scanner import FileScanner
from trailframe.services.scanners.scanner import Scanner
from trailframe.services.scanners.thumbnail_scanner import ThumbnailScanner


class CreationPipeline(Pipeline):
    _scanners: ClassVar[list[Scanner]] = [FileScanner(), ExifScanner(), ThumbnailScanner(), DatabaseScanner()]

