from __future__ import annotations

from datetime import UTC, datetime

from packaging.version import InvalidVersion, Version
from sqlmodel import select

from trailframe.models.migration import MigrationEvent
from trailframe.version import app_version

from .plans import MIGRATION_PLANS


def _version(value: str) -> Version | None:
    try:
        return Version(value)
    except InvalidVersion:
        return None


async def run_migration_plans(session) -> None:
    current = app_version()
    current_v = _version(current) or Version("0.0.0")

    for plan in MIGRATION_PLANS:
        min_v = _version(plan.min_version)
        max_v = _version(plan.max_version)

        if min_v is None or max_v is None:
            continue

        if current_v < min_v or current_v > max_v:
            continue

        applied = await session.execute(
            select(MigrationEvent).where(MigrationEvent.plan_name == plan.name, MigrationEvent.kind == "plan")
        )
        if applied.first() is not None:
            continue

        await plan.run(session)

        session.add(
            MigrationEvent(
                plan_name=plan.name,
                kind="plan",
                applied_version=current,
                applied_at=datetime.now(UTC).isoformat(),
                description=getattr(plan, "description", None),
            )
        )
        await session.commit()
