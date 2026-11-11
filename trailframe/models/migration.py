from __future__ import annotations

from sqlmodel import Field, SQLModel


class MigrationEvent(SQLModel, table=True):
    __tablename__ = "migration_event"

    id: int | None = Field(default=None, primary_key=True)
    plan_name: str
    kind: str
    applied_version: str | None = None
    applied_at: str
    description: str | None = None
