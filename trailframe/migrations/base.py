from __future__ import annotations

from typing import Any


class MigrationPlan:
    name: str
    min_version: str
    max_version: str
    description: str | None = None

    async def run(self, session: Any) -> None:
        raise NotImplementedError
