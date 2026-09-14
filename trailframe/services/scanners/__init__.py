from dataclasses import dataclass

from trailframe.services.scanners.activity_scanner import ActivityScanner
from trailframe.services.scanners.database_scanner import DatabaseScanner
from trailframe.services.scanners.exif_scanner import ExifScanner
from trailframe.services.scanners.file_scanner import FileScanner
from trailframe.services.scanners.location_scanner import LocationScanner
from trailframe.services.scanners.object_scanner import ObjectScanner
from trailframe.services.scanners.perceptual_hash_scanner import PerceptualHashScanner
from trailframe.services.scanners.scanner import Scanner
from trailframe.services.scanners.thumbnail_scanner import ThumbnailScanner


@dataclass(frozen=True)
class ScannerDefinition:
    name: str
    cls: type[Scanner]
    can_be_disabled: bool | None = None
    can_be_remote: bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "can_be_disabled", self.cls._can_be_disabled if self.can_be_disabled is None else self.can_be_disabled
        )
        object.__setattr__(
            self, "can_be_remote", self.cls._can_be_remote if self.can_be_remote is None else self.can_be_remote
        )


SCANNER_DEFINITIONS: tuple[ScannerDefinition, ...] = (
    ScannerDefinition("Activity", ActivityScanner),
    ScannerDefinition("Database", DatabaseScanner),
    ScannerDefinition("EXIF", ExifScanner),
    ScannerDefinition("File", FileScanner),
    ScannerDefinition("Location", LocationScanner),
    ScannerDefinition("Object", ObjectScanner),
    ScannerDefinition("PerceptualHash", PerceptualHashScanner),
    ScannerDefinition("Thumbnail", ThumbnailScanner),
)

SCANNERS: dict[str, ScannerDefinition] = {definition.name: definition for definition in SCANNER_DEFINITIONS}


def get_scanner_definition(name: str) -> ScannerDefinition | None:
    return SCANNERS.get(name)


def create_scanner(name: str) -> Scanner | None:
    definition = SCANNERS.get(name)

    return definition.cls() if definition is not None else None


def get_scanner_definitions() -> list[dict]:
    return [
        {
            "name": definition.name,
            "can_be_disabled": definition.can_be_disabled,
            "can_be_remote": definition.can_be_remote,
        }
        for definition in SCANNER_DEFINITIONS
    ]
