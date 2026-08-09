from gallery.models.photo import Photo
from gallery.services.location_service import LocationService
from gallery.services.scanners.scanner import Scanner


class LocationScanner(Scanner):
    def __init__(self) -> None:
        super().__init__("Location")

    def accept(self, photo: Photo) -> bool:
        return (
            photo.latitude is not None
            and photo.longitude is not None
            and photo.wireframe is None
        )

    def scan(self, photo: Photo) -> None:
        if photo.latitude is None or photo.longitude is None:
            photo.wireframe = None
            return

        result = LocationService.locate(photo.latitude, photo.longitude)

        if result is None:
            photo.wireframe = None
            return

        country, location, level, units, focus, file_parts = result

        photo.country = country
        photo.location = location

        wireframe = LocationService.create_wireframe(level, units, focus, file_parts)

        if wireframe is not None:
            photo.wireframe = wireframe
