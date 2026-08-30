import math
from datetime import datetime

from PIL import ExifTags
from PIL.ExifTags import GPSTAGS, TAGS

from trailframe.models.photo import Photo
from trailframe.services.pipelines.item import Item
from trailframe.services.scanners.scanner import Scanner


class ExifScanner(Scanner):
    """
    Extract EXIF metadata and enrich a Photo object.
    """

    def __init__(self):
        super().__init__("EXIF")

    def accept_(self, photo: Photo) -> bool:
        return not photo.exif

    async def executePhoto(self, item: Item) -> bool:
        image = item.image

        if image is None:
            return False

        exif = image.getexif()

        if not exif:
            return False

        photo = item.photo

        photo.exif = {TAGS[tag_id]: str(value) for tag_id, value in exif.items() if tag_id in TAGS and tag_id is not ExifTags.Base.MakerNote}

        self._update_ifds(photo, exif)
        self._update_date(photo)
        self._update_location(photo, exif)

        return True

    def _update_ifds(self, photo, exif) -> None:
        exif_ifd = exif.get_ifd(ExifTags.Base.ExifOffset)

        if exif_ifd:
            for tag_id, value in exif_ifd.items():
                if tag_id in TAGS and tag_id is not ExifTags.Base.MakerNote:
                    photo.exif[TAGS[tag_id]] = str(value)

        gps_ifd = exif.get_ifd(ExifTags.Base.GPSInfo)

        if gps_ifd:
            for tag_id, value in gps_ifd.items():
                if tag_id in GPSTAGS:
                    photo.exif[GPSTAGS[tag_id]] = str(value)

    def _update_date(self, photo) -> None:
        value = photo.exif.get("DateTimeOriginal") or photo.exif.get("DateTimeDigitized") or photo.exif.get("DateTime")

        if value is None:
            return

        try:
            photo.date = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
        except ValueError:
            pass

    def _update_location(self, photo, exif) -> None:
        gps_info = exif.get_ifd(ExifTags.Base.GPSInfo)

        if not gps_info:
            return

        gps = {GPSTAGS.get(key, key): value for key, value in gps_info.items()}

        photo.latitude = self._convert_coordinate(gps.get("GPSLatitude"), gps.get("GPSLatitudeRef"))
        photo.longitude = self._convert_coordinate(gps.get("GPSLongitude"), gps.get("GPSLongitudeRef"))

        if photo.latitude is not None or photo.longitude is not None:
            photo.location_source = "EXIF"

    def _convert_coordinate(self, value, reference) -> float | None:
        if value is None or not reference:
            return None

        try:
            degrees, minutes, seconds = (float(part) for part in value)
        except (TypeError, ValueError, ZeroDivisionError):
            return None

        if any(math.isnan(part) for part in (degrees, minutes, seconds)):
            return None

        if degrees == 0 and minutes == 0 and seconds == 0:
            return None

        result = degrees + minutes / 60 + seconds / 3600
        if reference in ("S", "W"):
            result = -result

        return result
