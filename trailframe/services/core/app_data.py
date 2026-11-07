from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

TABLE = "app_data"

HARDWARE_DETECTION = "hardware_detection"


def read_value(database_path: Path, key: str) -> str | None:
    """Read a value without the DatabaseService (used while services are configured).

    The database file may not exist yet (first run) or the table may predate the
    record, in which case the value is simply missing.
    """
    path = Path(database_path)

    if not path.is_file():
        return None

    try:
        with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=1) as connection:
            row = connection.execute(f"SELECT value FROM {TABLE} WHERE key = ?", (key,)).fetchone()
    except sqlite3.Error:
        return None

    return row[0] if row else None


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
