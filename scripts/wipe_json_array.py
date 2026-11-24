"""Remove matching objects from a JSON array column in a SQLite table.

The script is deliberately generic: it finds array objects whose field matches a
value and removes only those objects. It defaults to a dry run; ``--apply`` is
required to write. On apply, a timestamped copy of the database is made first.

Tilt provenance example::

    python scripts/wipe_json_array.py --database gallery.db \
        --table photo --column processing \
        --match-field step --match-value tilt \
        --label-column path --dry-run

    python scripts/wipe_json_array.py --database gallery.db \
        --table photo --column processing \
        --match-field step --match-value tilt \
        --label-column path --apply

Older libraries may keep the same column on a ``photos`` table; pass the table
that actually contains the processing column.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _identifier(value: str) -> str:
    """Quote a simple SQL identifier, rejecting anything else."""
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid SQL identifier: {value!r}")

    return f'"{value}"'


def _parse_value(raw: str) -> Any:
    """Parse a CLI value as JSON, falling back to the literal string."""
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return raw


def _display_value(value: Any) -> str:
    """Render a match value compactly in the report."""
    if isinstance(value, str):
        return value

    return json.dumps(value, ensure_ascii=False)


def _same_value(left: Any, right: Any) -> bool:
    """Compare a stored JSON value with the requested match value."""
    left_number = isinstance(left, (int, float)) and not isinstance(left, bool)
    right_number = isinstance(right, (int, float)) and not isinstance(right, bool)

    if left_number and right_number:
        return float(left) == float(right)

    return type(left) is type(right) and left == right


def _load_array(raw: Any) -> tuple[list | None, str | None]:
    """Decode a SQLite JSON cell, returning the value and a skip reason."""
    if raw is None:
        return None, "NULL"

    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None, "invalid UTF-8"

    if not isinstance(raw, str):
        return None, f"unsupported SQLite type {type(raw).__name__}"

    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None, "invalid JSON"

    if not isinstance(value, list):
        return None, "not a JSON array"

    return value, None


def _columns(connection: sqlite3.Connection, table: str) -> dict[str, tuple]:
    rows = connection.execute(f"PRAGMA table_info({_identifier(table)})").fetchall()

    return {row[1]: row for row in rows}


def _identity_column(connection: sqlite3.Connection, table: str, requested: str | None) -> str:
    """Find a usable row identifier, preferring the single primary key."""
    columns = _columns(connection, table)

    if requested is not None:
        if requested != "rowid" and requested not in columns:
            raise ValueError(f"Unknown --id-column {requested!r} on table {table!r}")

        return requested

    primary = sorted(((row[1], row[5]) for row in columns.values() if row[5]), key=lambda item: item[1])

    if len(primary) == 1:
        return primary[0][0]

    if primary:
        raise ValueError(f"Table {table!r} has a composite primary key; pass --id-column")

    try:
        connection.execute(f"SELECT {_identifier('rowid')} FROM {_identifier(table)} LIMIT 1").fetchone()
    except sqlite3.Error as error:
        raise ValueError(f"Table {table!r} has no row identifier; pass --id-column") from error

    return "rowid"


def _backup(database: str) -> Path:
    """Copy the database before an applying run, with a timestamped name."""
    source = Path(database)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backup = source.with_name(f"{source.name}.bak.{stamp}")
    counter = 1

    while backup.exists():
        backup = source.with_name(f"{source.name}.bak.{stamp}-{counter}")
        counter += 1

    shutil.copy2(source, backup)

    return backup


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database", default="gallery.db", help="SQLite database file (default: gallery.db)")
    parser.add_argument("--table", required=True, help="Table holding the JSON array column")
    parser.add_argument("--column", required=True, help="JSON array column to edit")
    parser.add_argument("--match-field", required=True, help="Object field used to select entries")
    parser.add_argument("--match-value", required=True, help="Value to match (JSON literal or plain string)")
    parser.add_argument("--id-column", help="Row identifier; inferred from the primary key when omitted")
    parser.add_argument("--label-column", help="Optional human-readable column shown in the report")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Only report the rows (default)")
    mode.add_argument("--apply", action="store_true", help="Back up the database and write the changes")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    apply = args.apply

    try:
        table = _identifier(args.table)
        column = _identifier(args.column)
        _identifier(args.match_field)  # validate the field name as a plain identifier
        field_name = args.match_field
        label_column = _identifier(args.label_column) if args.label_column else None
        match_value = _parse_value(args.match_value)

        database = Path(args.database)

        if not database.is_file():
            raise ValueError(f"Database not found: {database}")

        with sqlite3.connect(database) as connection:
            columns = _columns(connection, args.table)

            if not columns:
                raise ValueError(f"Unknown table {args.table!r}")

            if args.column not in columns:
                raise ValueError(f"Unknown column {args.column!r} on table {args.table!r}")

            if args.label_column and args.label_column not in columns:
                raise ValueError(f"Unknown --label-column {args.label_column!r} on table {args.table!r}")

            identity = _identity_column(connection, args.table, args.id_column)
            select = f"SELECT {_identifier(identity)}, {column}"
            if label_column:
                select += f", {label_column}"
            rows = connection.execute(f"{select} FROM {table}").fetchall()

            updates: list[tuple[Any, str]] = []
            skipped: dict[str, int] = {}
            removed_total = 0

            for row in rows:
                row_id, raw = row[0], row[1]
                label = row[2] if label_column else None
                values, reason = _load_array(raw)

                if reason is not None:
                    skipped[reason] = skipped.get(reason, 0) + 1
                    continue

                assert values is not None
                kept: list[Any] = []
                removed = 0

                for item in values:
                    if isinstance(item, dict) and field_name in item and _same_value(item[field_name], match_value):
                        removed += 1
                    else:
                        kept.append(item)

                if removed == 0:
                    continue

                removed_total += removed
                updates.append((json.dumps(kept, ensure_ascii=False), row_id))
                label_text = f" {args.label_column}={label}" if args.label_column and label is not None else ""
                value_text = _display_value(match_value)
                print(
                    f"{args.table} {identity}={row_id}{label_text} removes {removed} object(s): "
                    f"{args.match_field}={value_text}"
                )

            backup: Path | None = None

            if apply:
                backup = _backup(args.database)
                update = f"UPDATE {table} SET {column} = ? WHERE {_identifier(identity)} = ?"
                connection.executemany(update, updates)

        for reason, count in sorted(skipped.items()):
            print(f"Skipped {count} row(s): {reason}")

        if apply:
            print(f"Updated {len(updates)} of {len(rows)} rows; removed {removed_total} object(s).")
            print(f"Backup: {backup}")
        else:
            print(f"Dry run: would update {len(updates)} of {len(rows)} rows; remove {removed_total} object(s).")

        return 0
    except (sqlite3.Error, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
