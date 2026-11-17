from dataclasses import dataclass

from trailframe.services.core.configuration_service import Node
from trailframe.services.processors.crop_processor import CropProcessor
from trailframe.services.processors.processor import ProcessingContext, Processor, ProcessorResult
from trailframe.services.processors.rescale_processor import RescaleProcessor
from trailframe.services.processors.tilt_processor import TiltProcessor


@dataclass(frozen=True)
class ProcessorDefinition:
    name: str
    cls: type[Processor]


# The chain order is fixed: the tilt correction publishes the angle, the crop
# consumes it, and the rescale produces the target-sized output last.
PROCESSOR_DEFINITIONS: tuple[ProcessorDefinition, ...] = (
    ProcessorDefinition("Tilt", TiltProcessor),
    ProcessorDefinition("Crop", CropProcessor),
    ProcessorDefinition("Rescale", RescaleProcessor),
)

PROCESSORS: dict[str, ProcessorDefinition] = {definition.name: definition for definition in PROCESSOR_DEFINITIONS}


def create_processors(config: Node) -> list[Processor]:
    """Instantiate and configure the processing chain in its fixed order."""
    processors = [definition.cls() for definition in PROCESSOR_DEFINITIONS]

    for processor in processors:
        processor.configure(config)

    return processors


__all__ = [
    "PROCESSORS",
    "PROCESSOR_DEFINITIONS",
    "ProcessingContext",
    "Processor",
    "ProcessorDefinition",
    "ProcessorResult",
    "create_processors",
]
