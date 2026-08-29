import psutil
from fastapi import APIRouter
from pydantic import BaseModel

from trailframe.models.scanner_stat import ScannerStatSummary
from trailframe.services.core.statistics_service import StatisticsService

router = APIRouter(prefix="/api/statistics", tags=["statistics"])


class FolderStat(BaseModel):
    name: str
    size: int


class StorageStats(BaseModel):
    database_size: int
    filesystem: list[FolderStat]


class ProcessStats(BaseModel):
    rss: int
    vms: int


@router.get("/scanners", response_model=list[ScannerStatSummary])
async def list_scanner_statistics() -> list[ScannerStatSummary]:
    return await StatisticsService.get_scanner_summary()


@router.get("/storage", response_model=StorageStats)
async def get_storage_statistics() -> StorageStats:
    return StorageStats(
        database_size=StatisticsService.get_database_size(),
        filesystem=[FolderStat(**entry) for entry in StatisticsService.get_folder_sizes()],
    )


@router.get("/process", response_model=ProcessStats)
async def get_process_statistics() -> ProcessStats:
    mem = psutil.Process().memory_info()
    return ProcessStats(rss=mem.rss, vms=mem.vms)
