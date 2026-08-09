from sqlalchemy import func, select

from gallery.models.scanner_stat import ScannerStat, ScannerStatSummary
from gallery.services.database_service import DatabaseService
from gallery.services.service import Service


class ScannerStatsService(Service):
    @classmethod
    async def record_run(cls, stats: list[dict]) -> None:
        async with DatabaseService.create_session() as session:
            for stat in stats:
                session.add(
                    ScannerStat(
                        scanner=stat["scanner"],
                        count=stat["count"],
                        total_ms=stat["total_ms"],
                    )
                )

            await session.commit()

    @classmethod
    async def get_summary(cls) -> list[ScannerStatSummary]:
        async with DatabaseService.create_session() as session:
            result = await session.execute(
                select(
                    ScannerStat.scanner,
                    func.sum(ScannerStat.count),
                    func.sum(ScannerStat.total_ms),
                )
                .group_by(ScannerStat.scanner)
                .order_by(ScannerStat.scanner.asc())
            )
            rows = result.all()

        summary: list[ScannerStatSummary] = []

        for scanner, items, total_ms in rows:
            summary.append(
                ScannerStatSummary(
                    name=scanner,
                    items=items,
                    value=items / (total_ms / 1000) if total_ms > 0 else 0.0,
                )
            )

        return summary
