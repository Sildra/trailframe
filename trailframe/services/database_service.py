from pathlib import Path

from sqlalchemy import JSON, event, inspect, text
from sqlalchemy.dialects import sqlite
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateColumn
from sqlalchemy.types import Boolean, DateTime, Float, Integer, Numeric
from sqlmodel import SQLModel

from trailframe.models.activity import Activity, GarminActivity  # noqa: F401  (registers models with SQLModel metadata)
from trailframe.models.group import PhotoGroup  # noqa: F401  (registers models with SQLModel metadata)
from trailframe.models.photo import Photo  # noqa: F401  (registers models with SQLModel metadata)
from trailframe.models.scanner_stat import ScannerStat  # noqa: F401  (registers models with SQLModel metadata)
from trailframe.services.configuration_service import Node
from trailframe.services.service import Service


class DatabaseService(Service):
    _engine = None
    _session_factory = None

    @classmethod
    def _configure(cls, config: Node) -> None:
        cls._engine = create_async_engine(
            f"sqlite+aiosqlite:///{config.get_path_value('database', 'SQLite database file', 'gallery.db')}", echo=False
        )

        cls._session_factory = async_sessionmaker(cls._engine, class_=AsyncSession, expire_on_commit=False)

    @classmethod
    async def _start(cls) -> None:
        cls._register_hamming()
        async with cls._engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)
            await connection.run_sync(cls._add_missing_columns)
            await connection.run_sync(cls._sync_indexes)

    @classmethod
    def _register_hamming(cls) -> None:
        @event.listens_for(cls._engine.sync_engine, "connect")
        def _on_connect(dbapi_conn, _connection_record):
            dbapi_conn.create_function("hamming", 2, lambda a, b: (int.from_bytes(a, "big") ^ int.from_bytes(b, "big")).bit_count())

    @classmethod
    def _add_missing_columns(cls, connection) -> None:
        inspector = inspect(connection)
        existing = {
            table: {column["name"] for column in inspector.get_columns(table)}
            for table in inspector.get_table_names()
        }

        for table in SQLModel.metadata.sorted_tables:
            present = existing.get(table.name)

            if present is None:
                continue

            for column in table.columns:
                if column.name in present:
                    continue

                ddl = str(CreateColumn(column).compile(dialect=sqlite.dialect())).strip()

                if not column.nullable and column.server_default is None:
                    ddl += f" DEFAULT {cls._sqlite_default(column)}"

                connection.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {ddl}"))
                cls._log(f"added column {table.name}.{column.name}")

    @classmethod
    def _sync_indexes(cls, connection) -> None:
        inspector = inspect(connection)
        existing = {
            table: {index["name"] for index in inspector.get_indexes(table)}
            for table in inspector.get_table_names()
        }

        for table in SQLModel.metadata.sorted_tables:
            db_indexes = existing.get(table.name)

            if db_indexes is None:
                continue

            expected = {index.name: index for index in table.indexes if index.name is not None}

            for name, index in expected.items():
                if name in db_indexes:
                    continue

                unique = "UNIQUE " if index.unique else ""
                columns = ", ".join(index.columns.keys())
                connection.execute(text(f"CREATE {unique}INDEX {name} ON {table.name} ({columns})"))
                cls._log(f"created index {name} on {table.name}")

            for name in db_indexes:
                if name in expected:
                    continue

                connection.execute(text(f"DROP INDEX {name}"))
                cls._log(f"dropped index {name} on {table.name}")

    @staticmethod
    def _sqlite_default(column) -> str:
        if isinstance(column.type, Boolean):
            return "0"

        if isinstance(column.type, DateTime):
            return "'1970-01-01 00:00:00'"

        if isinstance(column.type, (Integer, Float, Numeric)):
            return "0"

        if isinstance(column.type, JSON):
            return "'[]'"

        return "''"

    @classmethod
    async def _stop(cls) -> None:
        if cls._engine:
            await cls._engine.dispose()

    @classmethod
    def create_session(cls) -> AsyncSession:
        return cls._session_factory()

    @classmethod
    def get_database_path(cls) -> Path:
        if cls._engine is None:
            return Path("gallery.db")

        return Path(cls._engine.url.database)

    @classmethod
    async def get_session(cls):
        async with cls._session_factory() as session:
            yield session
