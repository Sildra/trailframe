import os
from pathlib import Path
from typing import ClassVar

from sqlalchemy import func, select

from trailframe.models.scanner_stat import ScannerStat, ScannerStatSummary
from trailframe.services.core.configuration_service import Node
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.service import Service


class StatisticsService(Service):
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
    async def record_run(cls, stats: list[dict]) -> None:
        async with DatabaseService.create_session() as session:
            for stat in stats:
                session.add(ScannerStat(scanner=stat["scanner"], count=stat["count"], total_ms=stat["total_ms"]))

            await session.commit()

    @classmethod
    async def get_scanner_summary(cls) -> list[ScannerStatSummary]:
        async with DatabaseService.create_session() as session:
            result = await session.execute(
                select(ScannerStat.scanner, func.sum(ScannerStat.count), func.sum(ScannerStat.total_ms))
                .group_by(ScannerStat.scanner)
                .order_by(ScannerStat.scanner.asc())
            )
            rows = result.all()

        summary: list[ScannerStatSummary] = []

        for scanner, items, total_ms in rows:
            summary.append(
                ScannerStatSummary(name=scanner, items=items, value=items / (total_ms / 1000) if total_ms > 0 else 0.0)
            )

        return summary

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
