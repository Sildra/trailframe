from dataclasses import dataclass

from trailframe.services.core.configuration_service import Node
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


def read_scanner_configs(config: Node) -> None:
    """Materialize the `scanners` configuration subtree from every registered scanner.

    Creates a `scanners.<Name>` node for each flag-bearing scanner (one that can be
    disabled or run remotely), in registration order, tagging it with the scanner
    definition and populating its enabled/remote flags and per-scanner options with
    their defaults so the config surface is visible before pipelines are read.
    """
    for definition in SCANNER_DEFINITIONS:
        if not definition.can_be_disabled and not definition.can_be_remote:
            continue

        definition.cls().configure(config)


def create_scanner(name: str) -> Scanner | None:
    definition = SCANNERS.get(name)

    return definition.cls() if definition is not None else None


def can_run_remotely(name: str) -> bool:
    """Whether a scanner type is code-capable of remote execution.

    A static capability shared by every instance; it does not consult any
    configuration. The per-instance opt-in (`scanners.<Name>.enable_remote`)
    is enforced only by the server that actually executes the scanner
    (see `remote_enabled`), never by a host that merely delegates to it.
    """
    definition = SCANNERS.get(name)

    return definition is not None and definition.can_be_remote


def remote_enabled(name: str) -> bool:
    """Whether a scanable scanner may be executed on this server via remote-scan.

    Gates remote-capable scanners behind `scanners.<Name>.enable_remote`
    (default off) on the *remote* instance that runs the scanner; checked by
    the remote-scan endpoint only, never by a delegating host.
    """
    from trailframe.services.core.configuration_service import ConfigurationService

    definition = SCANNERS.get(name)

    if definition is None or not definition.can_be_remote:
        return False

    return bool(
        ConfigurationService.root().get_path_value(
            f"scanners.{name}.enable_remote", f"Enable {name} scanner for remote execution", False
        )
    )


def get_scanner_definitions() -> list[dict]:
    return [
        {
            "name": definition.name,
            "can_be_disabled": definition.can_be_disabled,
            "can_be_remote": definition.can_be_remote,
        }
        for definition in SCANNER_DEFINITIONS
    ]
