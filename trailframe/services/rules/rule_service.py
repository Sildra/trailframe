"""Stores rules on the tag rows and evaluates them against the library.

A rule is a small JSON document embedded in the `rules` column of the tag it
assigns. The tag is therefore the rule's target: renaming or moving a tag
carries its rules, and deleting a tag deletes them, so a rule can never point at
a path that no longer exists.

The enabled rules are kept in memory so `RulesScanner` can evaluate a photo
without a database round-trip.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, ClassVar

from pydantic import BaseModel, Field
from sqlalchemy import select, text

from trailframe.models.photo import Photo
from trailframe.models.tag import Tag
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.photos.tag_service import TagService
from trailframe.services.rules import evaluator, schema
from trailframe.services.rules.ast import Definition
from trailframe.services.rules.schema import RuleValidationError, validate_definition
from trailframe.services.service import Service


class RuleRecord(BaseModel):
    """The stored body of a rule; the owning tag supplies the target path."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str
    description: str = ""
    enabled: bool = True
    priority: int = 0
    expression: str = ""
    definition: Definition


@dataclass(frozen=True, slots=True)
class CachedRule:
    """An enabled rule as the scanner sees it."""

    id: str
    tag: str
    definition: Definition


class RuleService(Service):
    """Rule CRUD, the evaluator cache and the library-wide operations."""

    _requires = ("DatabaseService", "TagService")

    _records: ClassVar[list[tuple[str, RuleRecord]]] = []
    """Every stored rule, paired with the path of the tag that owns it."""

    _rules: ClassVar[list[CachedRule]] = []
    """The enabled rules, in evaluation order."""

    _values_cache: ClassVar[tuple[float, dict[str, list[str]]] | None] = None

    MAX_RULES = 200
    MAX_CONDITIONS = schema.MAX_CONDITIONS
    TEST_SCAN_LIMIT = 5000
    VALUES_TTL = 60.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    async def _start(cls) -> None:
        await cls.refresh()

    @classmethod
    async def refresh(cls) -> None:
        """Reload every tag's rules into memory."""

        async def _load(session) -> list[tuple[str, RuleRecord]]:
            rows = list((await session.execute(select(Tag).order_by(Tag.path))).scalars().all())
            records: list[tuple[str, RuleRecord]] = []

            for row in rows:
                for raw in row.rules or []:
                    try:
                        record = RuleRecord.model_validate(raw)
                    except ValueError:
                        continue

                    records.append((row.path, record))

            return records

        cls._records = await DatabaseService.execute(_load)
        cls._rules = [CachedRule(record.id, tag, record.definition) for tag, record in cls._records if record.enabled]
        cls._values_cache = None

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    @classmethod
    def _serialize(cls, tag: str, record: RuleRecord) -> dict[str, Any]:
        return {"tag": tag, **record.model_dump()}

    @classmethod
    async def list(cls) -> list[dict[str, Any]]:
        ordered = sorted(cls._records, key=lambda item: (item[0], item[1].priority, item[1].name.casefold()))

        return [cls._serialize(tag, record) for tag, record in ordered]

    @classmethod
    async def get(cls, rule_id: str) -> dict[str, Any] | None:
        for tag, record in cls._records:
            if record.id == rule_id:
                return cls._serialize(tag, record)

        return None

    @classmethod
    def cached_rules(cls) -> list[CachedRule]:
        """The enabled rules currently in memory, for the scanner."""
        return list(cls._rules)

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    @classmethod
    def validate(cls, payload: dict[str, Any]) -> RuleRecord:
        """Normalize a rule payload and reject the malformed ones."""
        name = str(payload.get("name") or "").strip()

        if not name:
            raise RuleValidationError("The rule needs a name")

        definition = payload.get("definition")

        if not isinstance(definition, Definition):
            try:
                definition = Definition.model_validate(definition)
            except ValueError as exception:
                raise RuleValidationError("The rule definition is malformed") from exception

        validate_definition(definition)

        priority = payload.get("priority", 0)

        try:
            priority = int(priority)
        except (TypeError, ValueError) as exception:
            raise RuleValidationError("`priority` must be an integer") from exception

        rule_id = str(payload.get("id") or uuid.uuid4().hex)

        return RuleRecord(
            id=rule_id,
            name=name,
            description=str(payload.get("description") or ""),
            enabled=bool(payload.get("enabled", True)),
            priority=priority,
            expression=str(payload.get("expression") or ""),
            definition=definition,
        )

    @classmethod
    async def _tag_path(cls, raw: str) -> str:
        path = TagService.normalize(str(raw or ""))

        if not path:
            raise RuleValidationError("The rule needs a tag")

        if TagService.depth_of(path) + 1 > TagService.MAX_DEPTH:
            raise RuleValidationError(f"The tag path is too deep (max {TagService.MAX_DEPTH} levels): {path}")

        await TagService.ensure_paths([path])

        return path

    @classmethod
    async def create(cls, payload: dict[str, Any]) -> dict[str, Any]:
        tag = await cls._tag_path(str(payload.get("tag") or ""))
        record = cls.validate({**payload, "id": uuid.uuid4().hex})

        async def _create(session) -> None:
            row = (await session.execute(select(Tag).where(Tag.path == tag))).scalar_one()
            row.rules = [*(row.rules or []), record.model_dump()]
            await session.commit()

        await DatabaseService.execute(_create)
        await cls.refresh()

        return cls._serialize(tag, record)

    @classmethod
    async def _locate(cls, rule_id: str) -> tuple[str, RuleRecord] | None:
        for tag, record in cls._records:
            if record.id == rule_id:
                return tag, record

        return None

    @classmethod
    async def update(cls, rule_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        found = await cls._locate(rule_id)

        if found is None:
            return None

        old_tag, _ = found
        tag = await cls._tag_path(str(payload.get("tag") or old_tag))
        record = cls.validate({**payload, "id": rule_id})

        async def _update(session) -> None:
            rows = list((await session.execute(select(Tag))).scalars().all())
            by_path = {row.path: row for row in rows}
            old_row = by_path[old_tag]
            new_row = by_path[tag]

            old_row.rules = [item for item in (old_row.rules or []) if item.get("id") != rule_id]
            new_row.rules = [*(new_row.rules or []), record.model_dump()]

            await session.commit()

        await DatabaseService.execute(_update)
        await cls.refresh()

        return cls._serialize(tag, record)

    @classmethod
    async def delete(cls, rule_id: str) -> bool:
        found = await cls._locate(rule_id)

        if found is None:
            return False

        tag, _ = found

        async def _delete(session) -> None:
            row = (await session.execute(select(Tag).where(Tag.path == tag))).scalar_one()
            row.rules = [item for item in (row.rules or []) if item.get("id") != rule_id]
            await session.commit()

        await DatabaseService.execute(_delete)
        await cls.refresh()

        return True

    # ------------------------------------------------------------------
    # Schema and suggestions
    # ------------------------------------------------------------------

    @classmethod
    def fields(cls) -> dict[str, Any]:
        """The photo schema the editor renders and hints from."""
        return schema.schema()

    @classmethod
    async def values(cls) -> dict[str, list[str]]:
        """Bounded value dictionaries for the suggestion popups (cached)."""
        now = time.monotonic()

        if cls._values_cache is not None and now - cls._values_cache[0] < cls.VALUES_TTL:
            return cls._values_cache[1]

        async def _values(session) -> dict[str, list[str]]:
            result: dict[str, list[str]] = {}

            for path, key in (("exif.Make", "Make"), ("exif.Model", "Model"), ("exif.LensModel", "LensModel")):
                rows = await session.execute(
                    text(
                        f"SELECT DISTINCT json_extract(exif, '$.\"{key}\"') AS value FROM {Photo.__tablename__} "
                        f"WHERE value IS NOT NULL AND value != '' ORDER BY value LIMIT 100"
                    )
                )
                result[path] = [str(row[0]) for row in rows.all()]

            for path, column in (("country", Photo.country), ("location", Photo.location)):
                rows = await session.execute(
                    select(column).where(column.is_not(None), column != "").distinct().order_by(column).limit(100)
                )
                result[path] = [str(row[0]) for row in rows.all()]

            rows = await session.execute(
                text(
                    f"SELECT DISTINCT json_extract(value, '$.label') AS label FROM {Photo.__tablename__}, "
                    "json_each(objects) WHERE label IS NOT NULL AND label != '' ORDER BY label LIMIT 200"
                )
            )
            result["objects"] = [str(row[0]) for row in rows.all()]

            rows = await session.execute(select(Tag.path).order_by(Tag.path))
            result["tags"] = [str(row[0]) for row in rows.all()]

            rows = await session.execute(
                text(
                    f"SELECT DISTINCT value FROM {Photo.__tablename__}, json_each(scanners) "
                    "WHERE value IS NOT NULL AND value != '' ORDER BY value LIMIT 100"
                )
            )
            result["scanners"] = [str(row[0]) for row in rows.all()]

            return result

        values = await DatabaseService.execute(_values)
        cls._values_cache = (now, values)

        return values

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    @classmethod
    def tags_for_photo(cls, photo: Photo) -> list[str]:
        """The tags every enabled rule assigns to `photo`."""
        return evaluator.tags_for_photo(photo, ((rule.tag, rule.definition) for rule in cls._rules))

    @classmethod
    def matches(cls, photo: Photo, definition: Definition) -> bool:
        return evaluator.matches(photo, definition)

    @classmethod
    async def preview(cls, tag: str, definition: Definition, limit: int = 24) -> dict[str, Any]:
        """Preview the photos a draft rule would tag, without writing anything."""
        path = TagService.normalize(tag)

        if not path:
            raise RuleValidationError("The rule needs a tag")

        definition = validate_definition(definition)

        async def _preview(session) -> dict[str, Any]:
            result = await session.execute(select(Photo).order_by(Photo.id).limit(cls.TEST_SCAN_LIMIT))
            photos = list(result.scalars().all())
            count = 0
            samples: list[dict[str, Any]] = []

            for photo in photos:
                if not evaluator.matches(photo, definition):
                    continue

                count += 1

                if len(samples) < max(0, limit):
                    samples.append({"photo_id": photo.id, "filename": photo.filename})

            return {"tag": path, "count": count, "truncated": len(photos) >= cls.TEST_SCAN_LIMIT, "photos": samples}

        return await DatabaseService.execute(_preview)

    @classmethod
    async def apply_all(cls) -> dict[str, int]:
        """Apply every enabled rule to the whole library (add-only)."""
        rules = cls._rules

        if not rules:
            return {"photos": 0, "changed": 0, "added": 0}

        paths: set[str] = set()

        async def _apply(session) -> dict[str, int]:
            result = await session.execute(select(Photo))
            photos = list(result.scalars().all())
            changed = 0
            added = 0

            for photo in photos:
                assigned = cls.tags_for_photo(photo)

                if not assigned:
                    continue

                tags = list(photo.tags or [])
                fresh = [path for path in assigned if path not in tags]

                if not fresh:
                    continue

                photo.tags = tags + fresh
                paths.update(fresh)
                changed += 1
                added += len(fresh)

            if changed:
                await session.commit()

            return {"photos": len(photos), "changed": changed, "added": added}

        result = await DatabaseService.execute(_apply)

        if paths:
            await TagService.ensure_paths(sorted(paths))

        return result


__all__ = ["CachedRule", "RuleRecord", "RuleService", "RuleValidationError"]
