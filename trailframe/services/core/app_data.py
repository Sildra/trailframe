from __future__ import annotations

from datetime import datetime

from sqlalchemy import text

TABLE = "app_data"


class AppData:
    """Read and write the misc data."""

    OBJECT_MODEL = "object_model"

    @staticmethod
    async def get_value(session, key: str) -> str | None:
        result = await session.execute(text(f"SELECT value FROM {TABLE} WHERE key = :key"), {"key": key})
        row = result.first()

        if row:
            return row[0]

        return None

    @staticmethod
    async def set_value(session, key: str, value: str) -> None:
        await session.execute(
            text(
                f"INSERT INTO {TABLE} (key, value, updated_at) VALUES (:key, :value, :now) ON CONFLICT(key) DO UPDATE SET value = :value, updated_at = :now"
            ),
            {"key": key, "value": value, "now": _now()},
        )


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")
