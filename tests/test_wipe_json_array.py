from __future__ import annotations

import json
import sqlite3

import allure
import pytest

from scripts.wipe_json_array import main


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "gallery.db"

    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE photo (id INTEGER PRIMARY KEY, path TEXT NOT NULL, processing TEXT)")
        connection.executemany(
            "INSERT INTO photo (id, path, processing) VALUES (?, ?, ?)",
            [
                (1, "a.jpg", json.dumps([{"step": "tilt"}, {"step": "rescale"}])),
                (2, "b.jpg", json.dumps([{"step": "rescale"}])),
                (3, "c.jpg", "not json"),
                (4, "d.jpg", json.dumps({"step": "tilt"})),
                (5, "e.jpg", json.dumps([{"step": "exposure"}, {"step": "tilt"}])),
            ],
        )

    return path


def _processing(database, photo_id: int) -> object:
    with sqlite3.connect(database) as connection:
        raw = connection.execute("SELECT processing FROM photo WHERE id = ?", (photo_id,)).fetchone()[0]

    return json.loads(raw)


def _arguments(database, *mode: str) -> list[str]:
    return [
        "--database",
        str(database),
        "--table",
        "photo",
        "--column",
        "processing",
        "--match-field",
        "step",
        "--match-value",
        "tilt",
        "--label-column",
        "path",
        *mode,
    ]


class TestWipeJsonArray:
    @allure.title("Dry run reports impacted rows without changing them")
    def test_dry_run(self, database, capsys):
        before = _processing(database, 1)

        assert main(_arguments(database, "--dry-run")) == 0

        output = capsys.readouterr().out
        assert "photo id=1 path=a.jpg removes 1 object(s): step=tilt" in output
        assert "photo id=5 path=e.jpg removes 1 object(s): step=tilt" in output
        assert "Dry run: would update 2 of 5 rows; remove 2 object(s)." in output
        assert "Skipped 1 row(s): invalid JSON" in output
        assert "Skipped 1 row(s): not a JSON array" in output
        assert _processing(database, 1) == before
        assert list(database.parent.glob("gallery.db.bak.*")) == []

    @allure.title("Apply removes only matching objects and keeps a backup")
    def test_apply(self, database, capsys):
        assert main(_arguments(database, "--apply")) == 0

        output = capsys.readouterr().out
        assert "Updated 2 of 5 rows; removed 2 object(s)." in output
        assert _processing(database, 1) == [{"step": "rescale"}]
        assert _processing(database, 2) == [{"step": "rescale"}]
        assert _processing(database, 5) == [{"step": "exposure"}]
        assert list(database.parent.glob("gallery.db.bak.*"))

    @allure.title("No matching object is a clean no-op")
    def test_no_match(self, tmp_path, capsys):
        path = tmp_path / "empty.db"

        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE photo (id INTEGER PRIMARY KEY, processing TEXT)")
            connection.execute("INSERT INTO photo (id, processing) VALUES (1, ?)", (json.dumps([{"step": "crop"}]),))

        arguments = [
            "--database",
            str(path),
            "--table",
            "photo",
            "--column",
            "processing",
            "--match-field",
            "step",
            "--match-value",
            "tilt",
            "--apply",
        ]

        assert main(arguments) == 0
        assert "Updated 0 of 1 rows; removed 0 object(s)." in capsys.readouterr().out
        assert _processing(path, 1) == [{"step": "crop"}]

    @allure.title("JSON literals keep numbers and booleans distinct")
    def test_typed_values(self, tmp_path, capsys):
        path = tmp_path / "typed.db"

        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE item (id INTEGER PRIMARY KEY, data TEXT)")
            connection.executemany(
                "INSERT INTO item (id, data) VALUES (?, ?)",
                [(1, json.dumps([{"score": 1}, {"score": True}])), (2, json.dumps([{"score": True}]))],
            )

        base = ["--database", str(path), "--table", "item", "--column", "data", "--match-field", "score"]

        assert main([*base, "--match-value", "1", "--dry-run"]) == 0
        output = capsys.readouterr().out
        assert "item id=1 removes 1 object(s): score=1" in output
        assert "id=2" not in output

        assert main([*base, "--match-value", "true", "--dry-run"]) == 0
        output = capsys.readouterr().out
        assert "item id=1 removes 1 object(s): score=true" in output
        assert "item id=2 removes 1 object(s): score=true" in output

    @allure.title("Unknown table and column names are rejected")
    def test_unknown_schema(self, database, capsys):
        assert main([*_arguments(database), "--table", "missing", "--dry-run"]) == 2
        assert "Unknown table" in capsys.readouterr().err

        assert main([*_arguments(database), "--column", "missing", "--dry-run"]) == 2
        assert "Unknown column" in capsys.readouterr().err
