import sqlite3

from trailframe.services.core.configuration_service import Node
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.core.thread_pool_service import ThreadPoolService

LEGACY_PHOTO_TABLE = """
CREATE TABLE "photo" (
    "id", "path", "filename", "file_size", "date", "source", "is_favorite", "latitude",
    "longitude", "location_source", "country", "location", "wireframe", "exif", "tags",
    "scores", "scanners", "objects", phash BLOB
)
"""


def _write_legacy_database(path) -> None:
    connection = sqlite3.connect(path)
    connection.execute(LEGACY_PHOTO_TABLE)
    connection.execute("CREATE UNIQUE INDEX ix_photo_path ON photo (path)")
    connection.executemany(
        "INSERT INTO photo (id, path, filename, date, is_favorite) VALUES (?, ?, ?, ?, 0)",
        [(1, "one.jpg", "one.jpg", "2026-01-01 10:00:00"), (None, "two.jpg", "two.jpg", "2026-01-02 10:00:00")],
    )
    connection.commit()
    connection.close()


async def _start_database_service(path) -> None:
    config = Node("root")
    config.get_node("general", "General parameters").get_node("database").set_value(str(path))

    ThreadPoolService.configure(config)
    await ThreadPoolService.start()
    DatabaseService.configure(config)
    await DatabaseService.start()


async def _stop_database_service() -> None:
    await DatabaseService.sync()
    await DatabaseService.stop()
    await ThreadPoolService.stop()


def _read(path, sql: str):
    connection = sqlite3.connect(path)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


class TestDatabaseService:
    async def test_rebuilds_table_saved_without_primary_key(self, tmp_path):
        database = tmp_path / "gallery.db"
        _write_legacy_database(database)

        await _start_database_service(database)

        try:
            primary_key = _read(database, "PRAGMA table_info(photo)")
            rows = _read(database, "SELECT id, path FROM photo ORDER BY path")
        finally:
            await _stop_database_service()

        assert [row[1] for row in primary_key if row[5]] == ["id"]
        assert rows == [(1, "one.jpg"), (2, "two.jpg")]
        assert (tmp_path / "gallery.db.bak").exists()

    async def test_rebuild_keeps_earlier_backups(self, tmp_path):
        database = tmp_path / "gallery.db"
        (tmp_path / "gallery.db.bak").write_text("previous backup", encoding="utf-8")
        _write_legacy_database(database)

        await _start_database_service(database)

        try:
            _read(database, "SELECT id, path FROM photo")
        finally:
            await _stop_database_service()

        assert (tmp_path / "gallery.db.bak").read_text(encoding="utf-8") == "previous backup"
        assert (tmp_path / "gallery.db.1.bak").exists()

    async def test_rebuild_restores_unique_index(self, tmp_path):
        database = tmp_path / "gallery.db"
        _write_legacy_database(database)

        await _start_database_service(database)

        try:
            indexes = _read(database, "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'photo'")
        finally:
            await _stop_database_service()

        assert ("ix_photo_path",) in indexes

    async def test_keeps_tables_already_matching_the_model(self, tmp_path):
        database = tmp_path / "gallery.db"

        await _start_database_service(database)

        try:
            tables = _read(database, "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
        finally:
            await _stop_database_service()

        assert ("photo",) in tables
        assert not (tmp_path / "gallery.db.bak").exists()
