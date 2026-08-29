from typing import Any

from trailframe.services.map.location_service import LocationService
from trailframe.services.scanners.scanner import Scanner


class LocationScanner(Scanner):
    def __init__(self) -> None:
        super().__init__("Location")

    def accept_(self, item: Any) -> bool:
        photo = item.photo

        return photo.latitude is not None and photo.longitude is not None and photo.wireframe is None

    async def executePhoto(self, item) -> bool:
        photo = item.photo

        if photo.latitude is None or photo.longitude is None:
            photo.wireframe = None

            return False

        result = LocationService.locate(photo.latitude, photo.longitude)

        if result is None:
            photo.wireframe = None

            return False

        country, location, level, units, focus, file_parts = result

        photo.country = country
        photo.location = location

        wireframe = LocationService.create_wireframe(level, units, focus, file_parts)

        if wireframe is not None:
            photo.wireframe = wireframe

        return True
