from __future__ import annotations

from sqlmodel import Field, SQLModel


class MigrationAudit(SQLModel, table=True):
    __tablename__ = "migration_audit"

    id: int | None = Field(default=None, primary_key=True)
    plan_name: str
    kind: str
    applied_version: str | None = None
    applied_at: str
    description: str | None = None


class MigrationPlanState(SQLModel, table=True):
    __tablename__ = "migration_plan_state"

    plan_name: str = Field(primary_key=True)
    applied_at: str
    applied_version: str | None = None
