import os
from pathlib import Path
from typing import ClassVar

from gallery.services.configuration_service import Node
from gallery.services.database_service import DatabaseService
from gallery.services.service import Service


class StorageService(Service):
    _folders: ClassVar[dict[str, Path]] = {}

    @classmethod
    def _configure(cls, config: Node) -> None:
        cls._folders = {
            "Photos": Path(config.get_path_value("photos_folder")),
            "Thumbnails": Path(config.get_path_value("thumbnails_folder")),
            "Maps": Path(config.get_path_value("maps_folder")),
            "Activities": Path(config.get_path_value("activities_folder")),
            "Models": Path(config.get_path_value("models_folder", default_value="models")),
            "Tiles": Path(config.get_path_value("tiles_folder", "Folder where cached map tiles are stored", "tiles")),
            "Trash": Path(config.get_path_value("trash_folder")),
        }

    @classmethod
    def get_database_size(cls) -> int:
        try:
            return DatabaseService.get_database_path().stat().st_size
        except OSError:
            return 0

    @classmethod
    def get_folder_sizes(cls) -> list[dict]:
        entries = [{"name": name, "size": cls._folder_size(folder)} for name, folder in cls._folders.items()]

        return sorted(entries, key=lambda entry: entry["size"], reverse=True)

    @staticmethod
    def _folder_size(folder: Path) -> int:
        if not folder.exists():
            return 0

        total = 0

        for root, _, files in os.walk(folder):
            for file in files:
                try:
                    total += (Path(root) / file).stat().st_size
                except OSError:
                    continue

        return total
