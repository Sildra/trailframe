from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, ClassVar

from sqlalchemy import select

from trailframe.models.photo import Photo
from trailframe.models.tag_rule import TagRule
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.photos.tag_service import TagService
from trailframe.services.service import Service


class TagRuleValidationError(ValueError):
    """Raised when a rule is not well formed."""


@dataclass(frozen=True, slots=True)
class RuleField:
    """One metadata field the rule builder can offer."""

    field: str
    group: str
    label: str
    description: str
    kind: str
    """`"objects"`, `"number"`, `"text"`, `"bool"`, `"date"` or `"list"`."""

    label_field: str | None = None
    """For `objects`: the field naming the detected label."""

    metrics: tuple[str, ...] = ()
    """For `objects`: the numeric metrics each detection exposes."""

    suggestions: tuple[str, ...] = ()
    """Sample values the builder offers for a text field."""


class TagRuleService(Service):
    """Assign tags to photos from their metadata, through user-defined rules.

    A rule is a small JSON document:

        {
          "name": "Dogs",
          "enabled": true,
          "priority": 10,
          "description": "Tag big, confident dog detections",
          "conditions": {
            "operator": "and",
            "rules": [
              {
                "field": "objects",
                "match_label": "dog",
                "constraints": {"confidence": {"gte": 0.8}, "surface": {"gte": 0.1}}
              }
            ]
          },
          "tags": ["Animals/Pet/Dog"]
        }

    `conditions.rules` are combined with `and`/`or`. A leaf names a metadata
    field, optionally an equality value, and a set of numeric/text constraints.
    Object rules additionally match on the detected label and expose the
    detection's `confidence` (0-1) and `surface` (share of the image area).

    Rules only ever *add* tags: they never remove one, so a tag a user set by
    hand is never taken away.
    """

    _requires = ("DatabaseService", "TagService")

    _rules: ClassVar[list[TagRule]] = []
    """The enabled rules, loaded once at start and refreshed after every write.

    Kept in memory so `RulesScanner` can evaluate a `Photo` without a database
    round-trip, the way every other scanner works.
    """

    MAX_RULES = 200
    MAX_CONDITIONS = 20
    TEST_SCAN_LIMIT = 5000
    """How many photos a rule preview walks through before giving up."""

    # Operators offered per field kind, with the frontend label and the unit.
    OPERATORS: ClassVar[dict[str, tuple[dict[str, str], ...]]] = {
        "number": (
            {"op": "gte", "label": "is at least"},
            {"op": "lte", "label": "is at most"},
            {"op": "gt", "label": "is more than"},
            {"op": "lt", "label": "is less than"},
            {"op": "eq", "label": "equals"},
            {"op": "neq", "label": "differs from"},
        ),
        "text": (
            {"op": "eq", "label": "is"},
            {"op": "neq", "label": "is not"},
            {"op": "contains", "label": "contains"},
            {"op": "in", "label": "is one of"},
        ),
        "bool": ({"op": "eq", "label": "is"}, {"op": "neq", "label": "is not"}),
        "date": ({"op": "gte", "label": "is on or after"}, {"op": "lte", "label": "is on or before"}),
        "list": ({"op": "contains", "label": "contains"},),
        "objects": ({"op": "present", "label": "is detected"}, {"op": "absent", "label": "is not detected"}),
    }

    NUMERIC_OPS: ClassVar[tuple[str, ...]] = ("eq", "neq", "gt", "gte", "lt", "lte")

    @classmethod
    def fields(cls) -> list[dict[str, Any]]:
        """The metadata catalog the assisted builder renders."""
        catalog = [
            RuleField(
                field="objects",
                group="Objects",
                label="Detected object",
                description="An object found by the Object scanner, with its confidence and the share of the image it covers.",
                kind="objects",
                label_field="label",
                metrics=("confidence", "surface"),
                suggestions=(
                    "dog",
                    "cat",
                    "person",
                    "car",
                    "bird",
                    "horse",
                    "bus",
                    "truck",
                    "bicycle",
                    "motorcycle",
                    "airplane",
                    "train",
                    "boat",
                    "backpack",
                    "umbrella",
                    "handbag",
                    "tie",
                    "suitcase",
                    "frisbee",
                    "skis",
                    "snowboard",
                    "sports ball",
                    "kite",
                    "skateboard",
                    "surfboard",
                    "tennis racket",
                    "bottle",
                    "wine glass",
                    "cup",
                    "fork",
                    "knife",
                    "spoon",
                    "bowl",
                    "banana",
                    "apple",
                    "sandwich",
                    "orange",
                    "broccoli",
                    "carrot",
                    "hot dog",
                    "pizza",
                    "donut",
                    "cake",
                    "chair",
                    "couch",
                    "potted plant",
                    "bed",
                    "dining table",
                    "toilet",
                    "tv",
                    "laptop",
                    "mouse",
                    "remote",
                    "keyboard",
                    "cell phone",
                    "microwave",
                    "oven",
                    "toaster",
                    "sink",
                    "refrigerator",
                    "book",
                    "clock",
                    "vase",
                    "scissors",
                    "teddy bear",
                    "hair drier",
                    "toothbrush",
                ),
            ),
            RuleField(
                field="exif.Make",
                group="Camera",
                label="Camera make",
                description="EXIF Make, the camera manufacturer.",
                kind="text",
                suggestions=("Apple", "Canon", "NIKON CORPORATION", "SONY", "FUJIFILM", "Panasonic", "Samsung"),
            ),
            RuleField(
                field="exif.Model",
                group="Camera",
                label="Camera model",
                description="EXIF Model, the camera or phone model.",
                kind="text",
            ),
            RuleField(field="exif.LensModel", group="Camera", label="Lens", description="EXIF LensModel.", kind="text"),
            RuleField(
                field="exif.FNumber",
                group="Camera",
                label="Aperture",
                description="EXIF FNumber, stored as text such as '28/10'.",
                kind="text",
            ),
            RuleField(
                field="exif.ISOSpeedRatings",
                group="Camera",
                label="ISO",
                description="EXIF ISOSpeedRatings.",
                kind="text",
            ),
            RuleField(
                field="exif.FocalLength",
                group="Camera",
                label="Focal length",
                description="EXIF FocalLength, stored as text such as '35/1'.",
                kind="text",
            ),
            RuleField(
                field="exif.ExposureTime",
                group="Camera",
                label="Exposure time",
                description="EXIF ExposureTime.",
                kind="text",
            ),
            RuleField(field="width", group="Image", label="Width", description="Image width in pixels.", kind="number"),
            RuleField(
                field="height", group="Image", label="Height", description="Image height in pixels.", kind="number"
            ),
            RuleField(
                field="orientation",
                group="Image",
                label="Orientation",
                description="`landscape`, `portrait` or `square`.",
                kind="text",
                suggestions=("landscape", "portrait", "square"),
            ),
            RuleField(
                field="location", group="Place", label="Location", description="Resolved place name.", kind="text"
            ),
            RuleField(field="country", group="Place", label="Country", description="Resolved country.", kind="text"),
            RuleField(
                field="date",
                group="Place",
                label="Date taken",
                description="Capture date, as `YYYY-MM-DD`.",
                kind="date",
            ),
            RuleField(
                field="filename",
                group="File",
                label="Filename",
                description="The file name, including its extension.",
                kind="text",
            ),
            RuleField(
                field="file_size", group="File", label="File size", description="File size in bytes.", kind="number"
            ),
            RuleField(
                field="is_favorite",
                group="File",
                label="Favorite",
                description="Whether the photo is marked as a favorite.",
                kind="bool",
            ),
            RuleField(
                field="tags",
                group="File",
                label="Current tags",
                description="The tags the photo already carries.",
                kind="list",
            ),
            RuleField(
                field="scores.brisque",
                group="Quality",
                label="Quality score",
                description="The BRISQUE score, when the quality scanner ran.",
                kind="number",
            ),
            RuleField(
                field="scanners",
                group="Other",
                label="Scanners run",
                description="The scanners that already processed the photo.",
                kind="list",
            ),
        ]

        return [
            {
                "field": item.field,
                "group": item.group,
                "label": item.label,
                "description": item.description,
                "kind": item.kind,
                "label_field": item.label_field,
                "metrics": list(item.metrics),
                "suggestions": list(item.suggestions),
                "operators": list(cls.OPERATORS.get(item.kind, ())),
            }
            for item in catalog
        ]

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @classmethod
    async def list(cls) -> list[TagRule]:
        async def _list(session) -> list[TagRule]:
            result = await session.execute(select(TagRule).order_by(TagRule.priority.desc(), TagRule.id))
            return list(result.scalars().all())

        return await DatabaseService.execute(_list)

    @classmethod
    async def get(cls, rule_id: int) -> TagRule | None:
        async def _get(session) -> TagRule | None:
            return await session.get(TagRule, rule_id)

        return await DatabaseService.execute(_get)

    @classmethod
    async def _start(cls) -> None:
        await cls.refresh()

    @classmethod
    async def refresh(cls) -> list[TagRule]:
        """Reload the enabled rules into memory (called at start and after every write)."""
        rules = await cls.list()
        cls._rules = [rule for rule in rules if rule.enabled]

        return cls._rules

    @classmethod
    def cached_rules(cls) -> list[TagRule]:
        """The enabled rules currently in memory, for the scanners."""
        return list(cls._rules)

    @classmethod
    async def test_rule(cls, rule: dict[str, Any], limit: int = 50) -> list[dict[str, Any]]:
        """Evaluate a draft rule against the photos already in the library.

        Read-only: it reports what the rule *would* tag, so the builder can
        preview a rule before saving it. Uses the same evaluation the scanner
        runs, with the rule kept out of the database.
        """
        clean = cls.validate(rule)
        draft = TagRule(**clean)

        async def _test(session) -> list[dict[str, Any]]:
            result = await session.execute(select(Photo).order_by(Photo.id).limit(cls.TEST_SCAN_LIMIT))
            matches: list[dict[str, Any]] = []

            for photo in result.scalars().all():
                tags = cls.matching_tags(photo, draft)

                if not tags:
                    continue

                matches.append({"photo_id": photo.id, "filename": photo.filename, "tags": tags})

                if len(matches) >= max(0, limit):
                    break

            return matches

        return await DatabaseService.execute(_test)

    @classmethod
    async def create(cls, rule: dict[str, Any]) -> TagRule:
        clean = cls.validate(rule)

        async def _create(session) -> TagRule:
            item = TagRule(**clean)
            session.add(item)
            await session.commit()
            await session.refresh(item)

            return item

        created = await DatabaseService.execute(_create)
        await cls.refresh()

        return created

    @classmethod
    async def update(cls, rule_id: int, rule: dict[str, Any]) -> TagRule | None:
        clean = cls.validate(rule)

        async def _update(session) -> TagRule | None:
            item = await session.get(TagRule, rule_id)

            if item is None:
                return None

            for key, value in clean.items():
                setattr(item, key, value)

            await session.commit()
            await session.refresh(item)

            return item

        updated = await DatabaseService.execute(_update)

        if updated is not None:
            await cls.refresh()

        return updated

    @classmethod
    async def delete(cls, rule_id: int) -> bool:
        async def _delete(session) -> bool:
            item = await session.get(TagRule, rule_id)

            if item is None:
                return False

            await session.delete(item)
            await session.commit()

            return True

        deleted = await DatabaseService.execute(_delete)

        if deleted:
            await cls.refresh()

        return deleted

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    @classmethod
    def tags_for_photo(cls, photo: Photo, rules: list[TagRule] | None = None) -> list[str]:
        """The tags every enabled rule assigns to `photo`, in priority order.

        Reads the rules held in memory, so a scanner can call it without a
        database round-trip.
        """
        if rules is None:
            rules = cls._rules

        assigned: list[str] = []

        for rule in rules:
            if not rule.enabled:
                continue

            for tag in cls.matching_tags(photo, rule):
                if tag not in assigned:
                    assigned.append(tag)

        return assigned

    @classmethod
    async def apply_all(cls) -> dict[str, int]:
        """Apply every enabled rule to the whole library.

        The counterpart of the `Rules` scanner for the photos that were already
        scanned: a rule created or edited after the fact only reaches them
        through this call. Like the scanner, it only ever adds a tag.
        """
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
                assigned = cls.tags_for_photo(photo, rules)

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

    @classmethod
    def matching_tags(cls, photo: Photo, rule: TagRule) -> list[str]:
        """The tags `rule` assigns to `photo` (empty when it does not match)."""
        if not cls.matches(photo, rule):
            return []

        values: list[str] = []

        for tag in rule.tags or []:
            path = TagService.normalize(str(tag))

            if path and path not in values:
                values.append(path)

        return values

    @classmethod
    def matches(cls, photo: Photo, rule: TagRule) -> bool:
        conditions = rule.conditions or {}
        children = conditions.get("rules") or []

        if not children:
            return False

        results = [cls.matches_condition(photo, child) for child in children if isinstance(child, dict)]

        if not results:
            return False

        if str(conditions.get("operator") or "and").lower() == "or":
            return any(results)

        return all(results)

    @classmethod
    def matches_condition(cls, photo: Photo, condition: dict[str, Any]) -> bool:
        field = str(condition.get("field") or "")
        constraints = condition.get("constraints") or {}
        op = str(condition.get("operator") or ("present" if field == "objects" else "eq"))
        expected = condition.get("value")

        if field == "objects":
            return cls._match_objects(photo, condition, constraints, op)
        if field == "exif" or field.startswith("exif."):
            return cls._match_value(cls._exif_value(photo, field), op, expected, constraints)
        if field.startswith("scores."):
            scores = photo.scores or {}
            return cls._match_value(scores.get(field.split(".", 1)[1]), op, expected, constraints)
        if field == "scanners":
            return cls._match_value(list(photo.scanners or []), op, expected, constraints)
        if field == "tags":
            return cls._match_value(list(photo.tags or []), op, expected, constraints)

        simple = cls._simple_value(photo, field)

        if simple is _MISSING:
            return False

        return cls._match_value(simple, op, expected, constraints)

    # ------------------------------------------------------------------
    # Field values
    # ------------------------------------------------------------------

    @classmethod
    def _simple_value(cls, photo: Photo, field: str) -> Any:
        if field == "filename":
            return photo.filename
        if field == "file_size":
            return photo.file_size
        if field == "is_favorite":
            return bool(photo.is_favorite)
        if field == "location":
            return photo.location
        if field == "country":
            return photo.country
        if field == "date":
            return photo.date.date().isoformat() if photo.date else None
        if field == "width":
            return cls.image_size(photo)[0]
        if field == "height":
            return cls.image_size(photo)[1]
        if field == "orientation":
            width, height = cls.image_size(photo)

            if not width or not height:
                return None

            if width == height:
                return "square"

            return "landscape" if width > height else "portrait"

        return _MISSING

    @classmethod
    def _exif_value(cls, photo: Photo, field: str) -> Any:
        exif = photo.exif or {}

        if field == "exif":
            return exif

        path = field.split(".", 1)[1]
        current: Any = exif

        for part in path.split("."):
            if not isinstance(current, dict):
                return None

            current = current.get(part)

        return current

    @classmethod
    def image_size(cls, photo: Photo) -> tuple[int | None, int | None]:
        """The pixel size of the photo, from the EXIF dimensions."""
        exif = photo.exif or {}
        width = cls._as_int(exif.get("ExifImageWidth") or exif.get("ImageWidth"))
        height = cls._as_int(exif.get("ExifImageHeight") or exif.get("ImageLength") or exif.get("ImageHeight"))

        if width and height:
            orientation = cls._as_int(exif.get("Orientation"))

            # EXIF orientations 5-8 swap the axes.
            if orientation in (5, 6, 7, 8):
                width, height = height, width

            return width, height

        return width, height

    @staticmethod
    def _as_int(value: Any) -> int | None:
        if value is None or isinstance(value, bool):
            return None

        if isinstance(value, (int, float)):
            return int(value)

        match = re.match(r"\s*(\d+)", str(value))

        return int(match.group(1)) if match else None

    # ------------------------------------------------------------------
    # Matching primitives
    # ------------------------------------------------------------------

    @classmethod
    def _match_objects(cls, photo: Photo, condition: dict[str, Any], constraints: dict[str, Any], op: str) -> bool:
        detections = cls._detections(photo, condition.get("match_label"))

        if op == "absent":
            return not detections

        if op == "present" and not constraints and condition.get("match_label"):
            # "is detected" matches any detection of the requested label.
            return bool(cls._detections(photo, condition.get("match_label"), ignore_constraints=True))

        if not detections:
            return False

        if not constraints:
            return True

        return any(cls._check_constraints(detection, constraints) for detection in detections)

    @classmethod
    def _detections(cls, photo: Photo, label: str | None, ignore_constraints: bool = False) -> list[dict[str, float]]:
        """The detections of the photo, with `confidence` and `surface` computed."""
        wanted = str(label).strip().lower() if label else None
        width, height = cls.image_size(photo)
        area = (width or 0) * (height or 0)
        detections: list[dict[str, float]] = []

        for raw in photo.objects or []:
            if not isinstance(raw, dict):
                continue

            detected = str(raw.get("label") or "")

            if wanted is not None and detected.lower() != wanted:
                continue

            confidence = cls._as_float(raw.get("confidence"))

            if confidence is None:
                confidence = 0.0

            surface = 0.0

            if area:
                box = raw.get("box") or []

                if isinstance(box, list) and len(box) == 4:
                    x1, y1, x2, y2 = (cls._as_float(part) or 0.0 for part in box)
                    surface = max(0.0, x2 - x1) * max(0.0, y2 - y1) / area

            detections.append(
                {
                    "label": detected,  # type: ignore[dict-item]
                    "confidence": confidence,
                    "score": confidence,
                    "surface": round(surface, 6),
                }
            )

        return detections

    @staticmethod
    def _as_float(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None

        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _check_constraints(cls, values: dict[str, Any], constraints: dict[str, Any]) -> bool:
        for metric, constraint in constraints.items():
            if metric not in values:
                continue

            if isinstance(constraint, dict):
                if not cls._compare(values[metric], constraint):
                    return False
            elif not cls._compare(values[metric], {"eq": constraint}):
                return False

        return True

    @classmethod
    def _match_value(cls, value: Any, op: str, expected: Any, constraints: dict[str, Any]) -> bool:
        if value is None and not isinstance(value, (list, dict)):
            return op == "neq"

        if constraints:
            if isinstance(value, dict):
                return cls._check_constraints(value, constraints)

            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return cls._compare(value, constraints)

        return cls._compare(value, {**({op: expected} if op not in cls.NUMERIC_OPS or expected is not None else {})})

    @classmethod
    def _compare(cls, value: Any, constraint: dict[str, Any]) -> bool:
        for op, expected in constraint.items():
            if op == "eq" and not cls._equals(value, expected):
                return False
            if op == "neq" and cls._equals(value, expected):
                return False
            if op == "contains" and not cls._contains(value, expected):
                return False
            if op == "in" and not cls._in(value, expected):
                return False
            if op in ("gt", "gte", "lt", "lte") and not cls._order(value, op, expected):
                return False

        return True

    @classmethod
    def _equals(cls, value: Any, expected: Any) -> bool:
        if isinstance(value, bool) or isinstance(expected, bool):
            return bool(value) == bool(expected)

        if isinstance(value, (int, float)) and isinstance(expected, (int, float)):
            return float(value) == float(expected)

        if isinstance(value, str) and isinstance(expected, str):
            return value.strip().lower() == expected.strip().lower()

        return value == expected

    @classmethod
    def _contains(cls, value: Any, expected: Any) -> bool:
        if isinstance(value, list):
            return any(cls._equals(item, expected) for item in value)

        if value is None:
            return False

        return str(expected).strip().lower() in str(value).lower()

    @classmethod
    def _in(cls, value: Any, expected: Any) -> bool:
        if not isinstance(expected, (list, tuple, set)):
            return False

        return any(cls._equals(value, item) for item in expected)

    @classmethod
    def _order(cls, value: Any, op: str, expected: Any) -> bool:
        left = cls._as_float(value)
        right = cls._as_float(expected)

        if left is None or right is None:
            # Fall back to a textual comparison for dates and EXIF ratios.
            if value is None or expected is None:
                return False

            left_text, right_text = str(value), str(expected)

            if op == "gt":
                return left_text > right_text
            if op == "gte":
                return left_text >= right_text
            if op == "lt":
                return left_text < right_text

            return left_text <= right_text

        if op == "gt":
            return left > right
        if op == "gte":
            return left >= right
        if op == "lt":
            return left < right

        return left <= right

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    _FIELD_NAMES: ClassVar[frozenset[str]] = frozenset(
        {
            "objects",
            "exif",
            "filename",
            "file_size",
            "is_favorite",
            "location",
            "country",
            "date",
            "width",
            "height",
            "orientation",
            "tags",
            "scanners",
        }
    )

    @classmethod
    def validate(cls, rule: dict[str, Any]) -> dict[str, Any]:
        """Normalize a rule and reject the malformed ones."""
        if not isinstance(rule, dict):
            raise TagRuleValidationError("The rule must be an object")

        name = str(rule.get("name") or "").strip()

        if not name:
            raise TagRuleValidationError("The rule needs a name")

        conditions = rule.get("conditions") or {}

        if not isinstance(conditions, dict):
            raise TagRuleValidationError("`conditions` must be an object")

        operator = str(conditions.get("operator") or "and").lower()

        if operator not in ("and", "or"):
            raise TagRuleValidationError("The condition operator must be 'and' or 'or'")

        children = conditions.get("rules")

        if not isinstance(children, list) or not children:
            raise TagRuleValidationError("The rule needs at least one condition")

        if len(children) > cls.MAX_CONDITIONS:
            raise TagRuleValidationError(f"A rule holds at most {cls.MAX_CONDITIONS} conditions")

        clean_children = [cls._validate_condition(child) for child in children]

        tags = rule.get("tags")

        if not isinstance(tags, list) or not tags:
            raise TagRuleValidationError("The rule needs at least one tag")

        clean_tags: list[str] = []

        for raw in tags:
            path = TagService.normalize(str(raw))

            if not path:
                raise TagRuleValidationError("A tag path cannot be empty")

            if TagService.depth_of(path) + 1 > TagService.MAX_DEPTH:
                raise TagRuleValidationError(f"The tag path is too deep (max {TagService.MAX_DEPTH} levels): {path}")

            if path not in clean_tags:
                clean_tags.append(path)

        priority = rule.get("priority", 0)

        try:
            priority = int(priority)
        except (TypeError, ValueError) as exception:
            raise TagRuleValidationError("`priority` must be an integer") from exception

        return {
            "name": name,
            "enabled": bool(rule.get("enabled", True)),
            "priority": priority,
            "description": (str(rule["description"]).strip() or None) if rule.get("description") else None,
            "conditions": {"operator": operator, "rules": clean_children},
            "tags": clean_tags,
        }

    @classmethod
    def _validate_condition(cls, condition: Any) -> dict[str, Any]:
        if not isinstance(condition, dict):
            raise TagRuleValidationError("Every condition must be an object")

        field = str(condition.get("field") or "").strip()

        if not field:
            raise TagRuleValidationError("Every condition needs a field")

        if not cls._is_known_field(field):
            raise TagRuleValidationError(f"Unknown metadata field: {field}")

        clean: dict[str, Any] = {"field": field}

        if field == "objects":
            label = condition.get("match_label")
            clean["match_label"] = str(label).strip().lower() if label else None
            clean["operator"] = "present" if str(condition.get("operator") or "present") == "present" else "absent"

            constraints = condition.get("constraints") or {}

            if not isinstance(constraints, dict):
                raise TagRuleValidationError("`constraints` must be an object")

            clean["constraints"] = cls._validate_constraints(constraints)

            return clean

        clean["operator"] = str(condition.get("operator") or "eq")
        clean["constraints"] = cls._validate_constraints(condition.get("constraints") or {})

        expected = condition.get("value")

        if expected is not None:
            clean["value"] = expected

        return clean

    @classmethod
    def _validate_constraints(cls, constraints: dict[str, Any]) -> dict[str, Any]:
        clean: dict[str, Any] = {}

        for metric, constraint in constraints.items():
            if constraint in (None, "", {}):
                continue

            if not isinstance(constraint, dict):
                raise TagRuleValidationError(f"The constraint on '{metric}' must be an object")

            cleaned: dict[str, Any] = {}

            for op, expected in constraint.items():
                if op not in (*cls.NUMERIC_OPS, "contains", "in"):
                    raise TagRuleValidationError(f"Unsupported comparison: {op}")

                if expected is None or expected == "":
                    continue

                if op in ("gt", "gte", "lt", "lte"):
                    try:
                        expected = float(expected)
                    except (TypeError, ValueError) as exception:
                        raise TagRuleValidationError(f"'{metric}' must be compared to a number") from exception

                cleaned[op] = expected

            if cleaned:
                clean[metric] = cleaned

        return clean

    @classmethod
    def _is_known_field(cls, field: str) -> bool:
        if field.startswith(("exif.", "scores.")):
            return len(field.split(".")) >= 2

        return field in cls._FIELD_NAMES


_MISSING = object()
