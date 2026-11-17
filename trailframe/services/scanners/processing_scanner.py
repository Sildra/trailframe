from trailframe.models.photo import Photo
from trailframe.services.photos.folder_service import FolderService
from trailframe.services.photos.processing_service import ProcessingService
from trailframe.services.pipelines.item import Item
from trailframe.services.scanners.scanner import Scanner


class ProcessingScanner(Scanner):
    """Preprocesses a freshly stored original into its processed alternatives.

    Runs in the pipeline after the metadata scanners and before the pixel
    consumers, so later scanners see `photo.main()` instead of the original.
    """

    _can_be_disabled = False

    def __init__(self) -> None:
        super().__init__("Processing")

    def accept_(self, photo: Photo) -> bool:
        return ProcessingService.needs_processing(photo)

    async def executePhoto(self, item: Item) -> bool:
        try:
            return await ProcessingService.preprocess(item.photo)
        except Exception:
            # Let the folder watcher retry the file on its next pass.
            FolderService.forget(item.photo.path)
            raise
