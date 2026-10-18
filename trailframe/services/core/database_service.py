import asyncio
import threading
from asyncio import AbstractEventLoop
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from typing import Any, ClassVar

from sqlalchemy import JSON, MetaData, event, inspect, text
from sqlalchemy.dialects import sqlite
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_scoped_session,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.schema import CreateColumn, CreateTable
from sqlalchemy.types import Boolean, DateTime, Float, Integer, Numeric
from sqlmodel import SQLModel

from trailframe.models.activity import Activity, GarminActivity  # noqa: F401  (registers models with SQLModel metadata)
from trailframe.models.group import PhotoGroup  # noqa: F401  (registers models with SQLModel metadata)
from trailframe.models.photo import Photo  # noqa: F401  (registers models with SQLModel metadata)
from trailframe.models.scanner_stat import ScannerStat  # noqa: F401  (registers models with SQLModel metadata)
from trailframe.services.core.configuration_service import Node
from trailframe.services.service import Service

Job = tuple[Callable[[Any], Any], Future | None]

_STOP = object()


async def _noop(session) -> None:
    return None


class DatabaseService(Service):
    """Run all SQL work on a dedicated database thread.

    Work is pushed onto a FIFO queue consumed by a single worker on the DB
    thread, so every operation runs sequentially and in submission order. The
    DB thread owns its own event loop and its own `async_scoped_session`
    (scoped to that thread), mirroring the thread-local `scoped_session` pattern.

    - `execute(fn)`: run `await fn(session)` on the DB thread and await the
      result (reads).
    - `execute_detached(fn)`: submit the same work without waiting for the
      result (writes); exceptions are logged.
    """

    _reconfig_safe = False
    _requires = ("ThreadPoolService",)

    _database_path: ClassVar[Path] = Path("gallery.db")
    _engine: ClassVar[AsyncEngine | None] = None
    _thread: ClassVar[threading.Thread | None] = None
    _loop: ClassVar[AbstractEventLoop | None] = None
    _queue: ClassVar[asyncio.Queue | None] = None
    _ScopedSession: ClassVar[Any | None] = None

    @classmethod
    def _configure(cls, config: Node) -> None:
        general_node = config.get_node("general", "General parameters")
        cls._database_path = Path(general_node.get_path_value("database", "SQLite database file", "gallery.db"))

    @classmethod
    async def _start(cls) -> None:
        cls._queue = asyncio.Queue()
        cls._loop = asyncio.new_event_loop()
        cls._thread = threading.Thread(target=cls._run, name="db", daemon=True)
        cls._thread.start()

        await cls.execute(_noop)

    @classmethod
    def _run(cls) -> None:
        asyncio.set_event_loop(cls._loop)
        cls._loop.run_until_complete(cls._bootstrap())

    @classmethod
    async def _bootstrap(cls) -> None:
        cls._engine = create_async_engine(f"sqlite+aiosqlite:///{cls._database_path}", echo=False)
        cls._register_hamming()

        cls._ScopedSession = async_scoped_session(
            async_sessionmaker(cls._engine, class_=AsyncSession, expire_on_commit=False), scopefunc=threading.get_ident
        )

        async with cls._engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)
            await connection.run_sync(cls._add_missing_columns)
            await connection.run_sync(cls._repair_primary_keys)
            await connection.run_sync(cls._sync_indexes)

        await cls._worker()

    @classmethod
    async def _worker(cls) -> None:
        while True:
            job = await cls._queue.get()

            if job is _STOP:
                cls._queue.task_done()
                break

            fn, future = job

            try:
                session = cls._ScopedSession()
                result = await fn(session)
            except Exception as exception:  # noqa: BLE001
                if future is not None and not future.cancelled():
                    future.set_exception(exception)
                elif future is None:
                    cls._log(f"detached DB job failed: {exception}")
            else:
                if future is not None and not future.cancelled():
                    future.set_result(result)
            finally:
                await cls._ScopedSession.remove()
                cls._queue.task_done()

    @classmethod
    def execute(cls, fn) -> Any:
        """Run `await fn(session)` on the DB thread and wait for the result."""
        future = Future()
        cls._enqueue(fn, future)

        return asyncio.wrap_future(future)

    @classmethod
    def execute_detached(cls, fn) -> None:
        """Submit `await fn(session)` to the DB thread without waiting (fire-and-forget)."""
        cls._enqueue(fn, None)

    @classmethod
    async def sync(cls) -> None:
        """Wait until every job already queued (including `execute_detached` writes) has run.

        Because the worker drains the FIFO queue in order, awaiting this barrier
        guarantees that all prior operations have completed on the DB thread.
        """
        await cls.execute(_noop)

    @classmethod
    def pending_jobs(cls) -> int:
        """Number of jobs still queued and not yet processed."""
        return cls._queue.qsize() if cls._queue is not None else 0

    @classmethod
    def _enqueue(cls, fn, future: Future | None) -> None:
        if cls._loop is None:
            raise RuntimeError("DatabaseService is not started")

        cls._loop.call_soon_threadsafe(cls._queue.put_nowait, (fn, future))

    @classmethod
    async def _dispose(cls, session) -> None:
        await session.close()
        await cls._engine.dispose()
        cls._engine = None

    @classmethod
    async def _stop(cls) -> None:
        if cls._loop is None:
            return

        await cls.execute(cls._dispose)
        cls._loop.call_soon_threadsafe(cls._queue.put_nowait, _STOP)

        if cls._thread is not None:
            cls._thread.join(timeout=5)
            cls._thread = None

        cls._loop = None
        cls._queue = None
        cls._ScopedSession = None

    @classmethod
    def _register_hamming(cls) -> None:
        @event.listens_for(cls._engine.sync_engine, "connect")
        def _on_connect(dbapi_conn, _connection_record):
            dbapi_conn.create_function(
                "hamming", 2, lambda a, b: (int.from_bytes(a, "big") ^ int.from_bytes(b, "big")).bit_count()
            )

    @classmethod
    def _add_missing_columns(cls, connection) -> None:
        inspector = inspect(connection)
        existing = {
            table: {column["name"] for column in inspector.get_columns(table)} for table in inspector.get_table_names()
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
    def _backup(cls, connection) -> None:
        path = str(cls._database_path)

        if ":memory:" in path or not cls._database_path.parent.exists():
            return

        backup = cls._free_backup_path(path)
        backup.unlink(missing_ok=True)

        try:
            connection.exec_driver_sql("VACUUM INTO ?", (str(backup),))
        except Exception as exception:  # noqa: BLE001
            cls._log(f"could not back up the database before rebuilding a table: {exception}")
            return

        cls._log(f"database backup written to {backup}")

    @staticmethod
    def _free_backup_path(path: str) -> Path:
        backup = Path(f"{path}.bak")
        index = 1

        while backup.exists():
            backup = Path(f"{path}.{index}.bak")
            index += 1

        return backup

    @classmethod
    def _rebuild_table(cls, connection, table, primary_key: list[str]) -> None:
        source = table.name
        target = f"{source}__rebuild"

        cls._backup(connection)

        inspector = inspect(connection)
        available = {info["name"] for info in inspector.get_columns(source)}
        columns = [column.name for column in table.columns if column.name in available]
        keys = ", ".join(f'"{name}"' for name in columns)
        values = ", ".join(f'"{name}"' for name in columns if name not in primary_key)

        connection.exec_driver_sql(f'DROP TABLE IF EXISTS "{target}"')
        connection.exec_driver_sql(
            str(CreateTable(table.to_metadata(MetaData(), name=target)).compile(dialect=sqlite.dialect()))
        )
        connection.exec_driver_sql(
            f'INSERT INTO "{target}" ({keys}) SELECT {keys} FROM "{source}" WHERE "{primary_key[0]}" IS NOT NULL'
        )

        if values:
            connection.exec_driver_sql(
                f'INSERT INTO "{target}" ({values}) SELECT {values} FROM "{source}" WHERE "{primary_key[0]}" IS NULL'
            )

        connection.exec_driver_sql(f'DROP TABLE "{source}"')
        connection.exec_driver_sql(f'ALTER TABLE "{target}" RENAME TO "{source}"')

        cls._log(f"rebuilt table {source} with primary key ({', '.join(primary_key)})")

    @classmethod
    def _repair_primary_keys(cls, connection) -> None:
        """Rebuild tables stored without the primary key their model declares.

        Databases created before a model declared a primary key keep the `NULL`
        id given on insert (SQLite only fills one in for an actual primary key),
        which leaves rows without identity: the scanner then merges them as new
        photos (`UNIQUE constraint failed: photo.path`) and every endpoint
        returning ids fails to validate. Rebuilding copies the rows over,
        re-keying the ones without an id.
        """
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())

        for table in SQLModel.metadata.sorted_tables:
            if table.name not in tables:
                continue

            primary_key = [column.name for column in table.primary_key.columns]

            if not primary_key or set(primary_key) == set(cls._database_primary_keys(inspector, table.name)):
                continue

            cls._rebuild_table(connection, table, primary_key)

            inspector = inspect(connection)
            tables = set(inspector.get_table_names())

    @staticmethod
    def _database_primary_keys(inspector, name: str) -> list[str]:
        try:
            constraint = inspector.get_pk_constraint(name) or {}
        except NoSuchTableError:
            return []

        return list(constraint.get("constrained_columns") or [])

    @classmethod
    def _sync_indexes(cls, connection) -> None:
        inspector = inspect(connection)
        existing = {
            table: {index["name"] for index in inspector.get_indexes(table)} for table in inspector.get_table_names()
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
    def get_database_path(cls) -> Path:
        return cls._database_path
