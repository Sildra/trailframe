from trailframe.models.photo import Photo
from trailframe.services.photos.tag_rule_service import TagRuleService
from trailframe.services.photos.tag_service import TagService
from trailframe.services.pipelines.item import Item
from trailframe.services.scanners.scanner import Scanner


class RulesScanner(Scanner):
    """Assign tags from the user-defined rules held by `TagRuleService`.

    Runs in the standard pipeline after the metadata scanners (EXIF, Object,
    Location, ...) and before `DatabaseScanner`, so the tags written here are
    persisted with the rest of the row. Rules only ever *add* a tag: a tag the
    user set by hand is never taken away.
    """

    _can_be_remote = False
    _definition = "Assign tags from the metadata rules configured in the Tags page"

    def __init__(self) -> None:
        super().__init__("Rules")

    def accept_(self, photo: Photo) -> bool:
        return "Rules" not in (photo.scanners or [])

    async def executePhoto(self, item: Item) -> bool:
        photo = item.photo
        assigned = TagRuleService.tags_for_photo(photo)

        if assigned:
            await TagService.ensure_paths(assigned)

            tags = list(photo.tags or [])

            for path in assigned:
                if path not in tags:
                    tags.append(path)

            photo.tags = tags

        self.add_scanner(photo)

        return bool(assigned)
