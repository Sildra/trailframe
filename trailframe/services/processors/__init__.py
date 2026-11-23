from dataclasses import dataclass

from trailframe.services.core.configuration_service import Node
from trailframe.services.processors.contrast_processor import ContrastOverride, ContrastProcessor
from trailframe.services.processors.crop_processor import CropProcessor
from trailframe.services.processors.exposure_processor import ExposureOverride, ExposureProcessor
from trailframe.services.processors.local_contrast_processor import LocalContrastOverride, LocalContrastProcessor
from trailframe.services.processors.noise_reduction_processor import NoiseReductionOverride, NoiseReductionProcessor
from trailframe.services.processors.processor import ProcessingContext, Processor, ProcessorResult
from trailframe.services.processors.rescale_processor import RescaleProcessor
from trailframe.services.processors.sharpening_processor import SharpeningOverride, SharpeningProcessor
from trailframe.services.processors.tilt_processor import TiltOverride, TiltProcessor
from trailframe.services.processors.vibrance_processor import VibranceOverride, VibranceProcessor
from trailframe.services.processors.white_balance_processor import WhiteBalanceOverride, WhiteBalanceProcessor


@dataclass(frozen=True)
class ProcessorDefinition:
    name: str
    cls: type[Processor]


# The chain order is fixed: colour and tone corrections come first, then the
# geometric tilt/crop pair, then noise reduction, the final resize and sharpening.
PROCESSOR_DEFINITIONS: tuple[ProcessorDefinition, ...] = (
    ProcessorDefinition("Exposure", ExposureProcessor),
    ProcessorDefinition("White balance", WhiteBalanceProcessor),
    ProcessorDefinition("Contrast", ContrastProcessor),
    ProcessorDefinition("Local contrast", LocalContrastProcessor),
    ProcessorDefinition("Vibrance", VibranceProcessor),
    ProcessorDefinition("Tilt", TiltProcessor),
    ProcessorDefinition("Crop", CropProcessor),
    ProcessorDefinition("Noise reduction", NoiseReductionProcessor),
    ProcessorDefinition("Rescale", RescaleProcessor),
    ProcessorDefinition("Sharpening", SharpeningProcessor),
)

PROCESSORS: dict[str, ProcessorDefinition] = {definition.name: definition for definition in PROCESSOR_DEFINITIONS}


PROCESSOR_OVERRIDES: dict[str, type] = {
    "Exposure": ExposureOverride,
    "White balance": WhiteBalanceOverride,
    "Contrast": ContrastOverride,
    "Local contrast": LocalContrastOverride,
    "Vibrance": VibranceOverride,
    "Tilt": TiltOverride,
    "Noise reduction": NoiseReductionOverride,
    "Sharpening": SharpeningOverride,
}


def create_processors(config: Node) -> list[Processor]:
    """Instantiate and configure the processing chain in its fixed order."""
    processors = [definition.cls() for definition in PROCESSOR_DEFINITIONS]

    for processor in processors:
        processor.configure(config)

    return processors


__all__ = [
    "PROCESSORS",
    "PROCESSOR_DEFINITIONS",
    "PROCESSOR_OVERRIDES",
    "ProcessingContext",
    "Processor",
    "ProcessorDefinition",
    "ProcessorResult",
    "create_processors",
]
