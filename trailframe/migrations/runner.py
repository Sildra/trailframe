from __future__ import annotations

from datetime import datetime, timezone

from packaging.version import Version
from sqlmodel import select

from trailframe.models.migration import MigrationAudit, MigrationPlanState
from trailframe.version import app_version

from .plans import MIGRATION_PLANS


async def run_migration_plans(session) -> None:
    current = app_version()
    try:
        current_v = Version(current)
    except Exception:
        current_v = Version("0.0.0")

    for plan in MIGRATION_PLANS:
        try:
            min_v = Version(plan.min_version)
            max_v = Version(plan.max_version)
        except Exception:
            continue

        if current_v < min_v or current_v > max_v:
            continue

        result = await session.execute(select(MigrationPlanState).where(MigrationPlanState.plan_name == plan.name))
        if result.first() is not None:
            continue

        await plan.run(session)

        now = datetime.now(timezone.utc).isoformat()
        session.add(MigrationPlanState(plan_name=plan.name, applied_at=now, applied_version=current))
        session.add(
            MigrationAudit(
                plan_name=plan.name,
                kind="plan",
                applied_version=current,
                applied_at=now,
                description=getattr(plan, "description", None),
            )
        )
        await session.commit()
