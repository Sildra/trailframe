from __future__ import annotations

from .base import MigrationPlan


class InitializeMigration(MigrationPlan):
    name = "initialize_migration"
    min_version = "0.0.0"
    max_version = "9999.0.0"
    description = "Initialize migration"

    async def run(self, session) -> None:
        pass


MIGRATION_PLANS: tuple[MigrationPlan, ...] = (InitializeMigration(),)
