from typing import Any, ClassVar

from sqlalchemy import and_, exists, func, null, or_, select, text
from sqlalchemy.sql.elements import ColumnElement

from trailframe.models.photo import Photo
from trailframe.models.tag import Tag, TagNode
from trailframe.services.core.configuration_service import ConfigurationService, Node
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.service import Service


class TagConflictError(ValueError):
    """Raised when a tag path is already taken by another tag."""


class TagService(Service):
    """Hierarchical tag registry and photo tagging.

    The registry (`tags` table) holds the *shape* of the vocabulary: one row per
    node, with its full slash-separated `path` and a link to its parent. The
    assignments live on the photos themselves (`Photo.tags`, a JSON list of full
    paths), so a tag is stored in exactly one place.

    Paths are the canonical form: "Architecture/Building/Church" is the path,
    "Church" its name, and "Architecture/Building" its parent. Any path can be
    matched with or without its descendants, which is what the photo filters
    use (`json_each` over `Photo.tags`).
    """

    _requires = ("DatabaseService",)

    SEPARATOR = "/"
    MAX_DEPTH = 10

    DEFAULT_TAGS: ClassVar[dict[str, dict]] = {
        "Activity": {"Sports": {}, "Travel": {}, "Family": {}, "Party": {}, "Work": {}},
        "Architecture": {
            "Building": {"Church": {}, "Castle": {}, "House": {}, "Skyscraper": {}},
            "Bridge": {},
            "Monument": {},
            "Ruins": {},
            "Interior": {},
        },
        "Landscape": {
            "Mountain": {"Peak": {}, "Valley": {}, "Glacier": {}},
            "Beach": {},
            "Forest": {},
            "Desert": {},
            "Field": {},
            "Water": {"Lake": {}, "River": {}, "Ocean": {}, "Waterfall": {}},
            "Sky": {"Sunset": {}, "Sunrise": {}, "Clouds": {}, "Stars": {}},
            "Urban": {"Street": {}, "City": {}},
        },
        "Animals": {
            "Pet": {"Cat": {}, "Dog": {}},
            "Wildlife": {
                "Lion": {},
                "Tiger": {},
                "Elephant": {},
                "Bear": {},
                "Deer": {},
                "Fox": {},
                "Horse": {},
                "Sheep": {},
                "Cow": {},
                "Zebra": {},
                "Giraffe": {},
            },
            "Bird": {},
            "Marine": {"Dolphin": {}, "Whale": {}, "Fish": {}},
            "Insect": {},
        },
        "People": {"Person": {}, "Group": {}, "Child": {}, "Crowd": {}},
        "Food": {"Meal": {}, "Drink": {}, "Dessert": {}, "Fruit": {}, "Vegetable": {}, "Tableware": {}},
        "Nature": {"Flower": {}, "Tree": {}, "Plant": {}, "Weather": {"Rain": {}, "Snow": {}, "Fog": {}, "Wind": {}}},
        "Transport": {
            "Car": {},
            "Bus": {},
            "Truck": {},
            "Bike": {},
            "Motorcycle": {},
            "Boat": {},
            "Plane": {},
            "Train": {},
        },
        "Object": {
            "Electronics": {"TV": {}, "Laptop": {}, "Mobile": {}, "Mouse": {}, "Keyboard": {}, "Remote": {}},
            "Furniture": {"Chair": {}, "Sofa": {}, "Bed": {}, "Table": {}, "Bench": {}},
            "Clothing": {"Backpack": {}, "Umbrella": {}, "Handbag": {}, "Tie": {}},
            "Luggage": {"Suitcase": {}},
            "Kitchen": {"Microwave": {}, "Oven": {}, "Toaster": {}, "Sink": {}, "Refrigerator": {}},
            "Sport": {
                "Ball": {},
                "Skateboard": {},
                "Surfboard": {},
                "Ski": {},
                "Snowboard": {},
                "Tennis Racket": {},
                "Frisbee": {},
                "Kite": {},
            },
            "Tool": {"Scissors": {}, "Toothbrush": {}, "Hair Drier": {}},
            "Decoration": {"Vase": {}, "Clock": {}},
            "Toy": {"Teddy Bear": {}},
            "Book": {},
            "Traffic Light": {},
            "Fire Hydrant": {},
            "Parking Meter": {},
            "Signage": {},
        },
        "Event": {"Wedding": {}, "Birthday": {}, "Holiday": {}, "Christmas": {}, "Concert": {}},
        "Document": {"Screenshot": {}, "Receipt": {}},
        "Quality": {"Panorama": {}, "Macro": {}, "Black and White": {}, "Low Light": {}, "Long Exposure": {}},
    }

    _seeded: ClassVar[bool] = False

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    @classmethod
    def normalize(cls, raw: str) -> str:
        """Canonical form of a tag path: trimmed segments, single separators."""
        segments = [segment.strip() for segment in str(raw or "").split(cls.SEPARATOR)]

        return cls.SEPARATOR.join(segment for segment in segments if segment)

    @classmethod
    def name_of(cls, path: str) -> str:
        return path.rsplit(cls.SEPARATOR, 1)[-1]

    @classmethod
    def parent_path(cls, path: str) -> str:
        return path.rsplit(cls.SEPARATOR, 1)[0] if cls.SEPARATOR in path else ""

    @classmethod
    def ancestors(cls, path: str) -> list[str]:
        """Every ancestor path of `path`, from the root down to its parent."""
        segments = path.split(cls.SEPARATOR)

        return [cls.SEPARATOR.join(segments[:index]) for index in range(1, len(segments))]

    @classmethod
    def depth_of(cls, path: str) -> int:
        return path.count(cls.SEPARATOR)

    @classmethod
    def is_under(cls, path: str, parent: str) -> bool:
        return path == parent or path.startswith(parent + cls.SEPARATOR)

    # ------------------------------------------------------------------
    # Configuration / lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def _configure(cls, config: Node) -> None:
        cls._seeded = bool(config.get_path_value("tags.seeded", "The default tag vocabulary has been installed", False))

    @classmethod
    async def _start(cls) -> None:
        if cls._seeded:
            return

        created = await cls.seed_defaults()
        cls._log(f"installed the default tag vocabulary ({created} tags)")

        ConfigurationService.root().get_node("tags.seeded").set_value(True)
        ConfigurationService.save()

    @classmethod
    async def seed_defaults(cls) -> int:
        """Install the default vocabulary. Existing paths are left untouched."""
        paths: list[str] = []

        def walk(nodes: dict[str, dict], prefix: str) -> None:
            for name, children in nodes.items():
                path = f"{prefix}{name}"
                paths.append(path)
                walk(children, f"{path}{cls.SEPARATOR}")

        walk(cls.DEFAULT_TAGS, "")

        _, created = await cls._ensure_paths(paths)

        return created

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    @classmethod
    def _values_table(cls):
        """SQLite `json_each` over the photo tag column, as a table-valued function."""
        return func.json_each(func.coalesce(Photo.tags, "[]")).table_valued("value")

    @classmethod
    def _escape_like(cls, value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    @classmethod
    def _path_clause(cls, values, path: str):
        prefix = f"{cls._escape_like(path)}{cls.SEPARATOR}%"

        return or_(values.c.value == path, values.c.value.like(prefix, escape="\\"))

    @classmethod
    def match(cls, paths: list[str], mode: str = "any") -> ColumnElement:
        """Condition matching the photos carrying `paths` (exactly, or below them).

        `mode` is "any" (a photo carrying one of the tags matches) or "all" (a
        photo must carry every one of them).
        """
        if not paths:
            return null()

        values = cls._values_table()
        clauses = [exists(select(1).select_from(values).where(cls._path_clause(values, path))) for path in paths]

        if mode == "all":
            return and_(*clauses)

        return or_(*clauses)

    @classmethod
    def _under_any(cls, value: str, paths: list[str]) -> bool:
        return any(cls.is_under(value, path) for path in paths)

    @classmethod
    def match_exact(cls, paths: list[str], mode: str = "any") -> ColumnElement:
        """Condition matching the photos carrying `paths` exactly, without descendants."""
        if not paths:
            return null()

        values = cls._values_table()
        clauses = [exists(select(1).select_from(values).where(values.c.value == path)) for path in paths]

        if mode == "all":
            return and_(*clauses)

        return or_(*clauses)

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------

    @classmethod
    async def _ensure_paths(cls, paths: list[str]) -> tuple[list[str], int]:
        normalized: list[str] = []

        for raw in paths:
            value = cls.normalize(raw)

            if value and value not in normalized:
                normalized.append(value)

        if not normalized:
            return [], 0

        wanted: set[str] = set()

        for value in normalized:
            wanted.add(value)
            wanted.update(cls.ancestors(value))

        async def _ensure(session) -> int:
            rows = list((await session.execute(select(Tag))).scalars().all())
            by_path = {row.path: row for row in rows}
            created = 0

            for depth in sorted({cls.depth_of(path) for path in wanted}):
                for path in sorted(path for path in wanted if cls.depth_of(path) == depth):
                    if path in by_path:
                        continue

                    parent = by_path.get(cls.parent_path(path))
                    tag = Tag(
                        name=cls.name_of(path),
                        path=path,
                        parent_id=parent.id if parent is not None else None,
                        depth=depth,
                    )

                    session.add(tag)
                    await session.flush()

                    by_path[path] = tag
                    rows.append(tag)
                    created += 1

            if created:
                await session.commit()

            return created

        created = await DatabaseService.execute(_ensure)

        return normalized, created

    @classmethod
    async def ensure_paths(cls, paths: list[str]) -> list[str]:
        """Register `paths` (and their ancestors) in the registry."""
        normalized, _ = await cls._ensure_paths(paths)

        return normalized

    @classmethod
    async def _counts(cls, session) -> dict[str, int]:
        table = Photo.__tablename__
        result = await session.execute(
            text(
                f"SELECT value AS path, COUNT(*) AS count FROM {table}, "
                f"json_each(COALESCE({table}.tags, '[]')) GROUP BY value"
            )
        )

        return {row[0]: row[1] for row in result.all()}

    @classmethod
    def _build_tree(cls, rows: list[Tag], counts: dict[str, int]) -> list[TagNode]:
        nodes: dict[int, TagNode] = {
            row.id: TagNode(
                id=row.id,
                name=row.name,
                path=row.path,
                depth=row.depth,
                description=row.description,
                count=counts.get(row.path, 0),
            )
            for row in rows
        }

        roots: list[TagNode] = []

        for row in rows:
            node = nodes[row.id]
            parent = nodes.get(row.parent_id) if row.parent_id is not None else None

            if parent is None:
                roots.append(node)
            else:
                parent.children.append(node)

        def total(node: TagNode) -> int:
            node.total = node.count + sum(total(child) for child in node.children)

            return node.total

        for root in roots:
            total(root)

        return roots

    @classmethod
    async def get_tree(cls) -> list[TagNode]:
        """The registry as a tree, with the number of photos using each node."""

        async def _tree(session) -> list[TagNode]:
            rows = list((await session.execute(select(Tag).order_by(Tag.path))).scalars().all())
            counts = await cls._counts(session)

            return cls._build_tree(rows, counts)

        return await DatabaseService.execute(_tree)

    # ------------------------------------------------------------------
    # Photo assignments
    # ------------------------------------------------------------------

    @classmethod
    async def _rewrite_photos(cls, session, old_path: str, new_path: str) -> int:
        """Move the tags under `old_path` (and `old_path` itself) to `new_path`."""
        result = await session.execute(select(Photo).where(cls.match([old_path])))
        photos = list(result.scalars().all())

        for photo in photos:
            photo.tags = [cls._rewrite_path(value, old_path, new_path) for value in (photo.tags or [])]

        return len(photos)

    @classmethod
    def _rewrite_path(cls, value: str, old_path: str, new_path: str) -> str:
        if value == old_path:
            return new_path

        if value.startswith(old_path + cls.SEPARATOR):
            return new_path + value[len(old_path) :]

        return value

    @classmethod
    async def _strip_photos(cls, session, paths: list[str]) -> int:
        """Remove every tag under `paths` from the photos carrying them."""
        if not paths:
            return 0

        result = await session.execute(select(Photo).where(cls.match(paths)))
        photos = list(result.scalars().all())

        for photo in photos:
            photo.tags = [value for value in (photo.tags or []) if not cls._under_any(value, paths)]

        return len(photos)

    @classmethod
    async def set_photo_tags(cls, photo_id: int, paths: list[str]) -> list[str] | None:
        """Replace the tags of a photo. Returns None when the photo is unknown."""
        normalized = await cls.ensure_paths(paths)

        async def _set(session) -> list[str] | None:
            photo = (await session.execute(select(Photo).where(Photo.id == photo_id))).scalar_one_or_none()

            if photo is None:
                return None

            photo.tags = normalized
            await session.commit()

            return normalized

        return await DatabaseService.execute(_set)

    @classmethod
    async def add_photo_tag(cls, photo_id: int, path: str) -> list[str] | None:
        normalized = await cls.ensure_paths([path])

        async def _add(session) -> list[str] | None:
            photo = (await session.execute(select(Photo).where(Photo.id == photo_id))).scalar_one_or_none()

            if photo is None:
                return None

            tags = list(photo.tags or [])

            for value in normalized:
                if value not in tags:
                    tags.append(value)

            photo.tags = tags
            await session.commit()

            return tags

        return await DatabaseService.execute(_add)

    @classmethod
    async def remove_photo_tag(cls, photo_id: int, path: str) -> list[str] | None:
        normalized = cls.normalize(path)

        async def _remove(session) -> list[str] | None:
            photo = (await session.execute(select(Photo).where(Photo.id == photo_id))).scalar_one_or_none()

            if photo is None:
                return None

            photo.tags = [value for value in (photo.tags or []) if not cls.is_under(value, normalized)]
            await session.commit()

            return photo.tags

        return await DatabaseService.execute(_remove)

    # ------------------------------------------------------------------
    # Registry mutations
    # ------------------------------------------------------------------

    @classmethod
    async def create(cls, path: str, description: str | None = None) -> list[TagNode]:
        """Register a single tag path, creating the missing ancestors.

        Unlike `sync`, which replaces the whole vocabulary, this adds one tag
        and leaves everything else untouched.
        """
        normalized = cls.normalize(path)

        if not normalized:
            raise ValueError("a tag path cannot be empty")

        if cls.depth_of(normalized) + 1 > cls.MAX_DEPTH:
            raise ValueError(f"tag path is too deep (max {cls.MAX_DEPTH} levels): {normalized}")

        entry = {"path": normalized, "description": str(description) if description else None}

        async def _create_one(session) -> None:
            rows = list((await session.execute(select(Tag))).scalars().all())
            by_path = {row.path: row for row in rows}

            if normalized in by_path:
                raise TagConflictError(f"a tag already exists at '{normalized}'")

            await cls._create(session, entry, by_path, rows)
            await session.commit()

            cls._log(f"added the tag '{normalized}'")

        await DatabaseService.execute(_create_one)

        return await cls.get_tree()

    @classmethod
    async def delete(cls, tag_id: int) -> dict[str, Any] | None:
        """Delete a tag and every descendant, stripping them from the photos."""

        async def _delete(session) -> dict[str, Any] | None:
            rows = list((await session.execute(select(Tag))).scalars().all())
            target = next((row for row in rows if row.id == tag_id), None)

            if target is None:
                return None

            paths = [row.path for row in rows if cls.is_under(row.path, target.path)]
            photos = await cls._strip_photos(session, paths)

            for row in rows:
                if row.path in paths:
                    await session.delete(row)

            await session.commit()

            return {"deleted": True, "tags": len(paths), "photos": photos}

        return await DatabaseService.execute(_delete)

    @classmethod
    async def sync(cls, payload: list[dict[str, Any]]) -> list[TagNode]:
        """Apply a whole vocabulary in one go.

        The payload is the complete list of tags the client wants to keep. Each
        entry carries the id it had on the server (when it is an existing tag)
        and the path it should now have: a changed path renames the tag, a
        missing entry deletes it (together with its descendants).
        """
        entries = cls._validate(payload)

        async def _sync(session) -> None:
            rows = list((await session.execute(select(Tag).order_by(Tag.path))).scalars().all())
            by_id = {row.id: row for row in rows}
            by_path = {row.path: row for row in rows}

            await cls._apply_renames(session, entries, rows, by_id, by_path)

            deleted = cls._deleted_paths(rows, by_id, by_path, entries)
            photos = await cls._strip_photos(session, deleted)

            for row in rows:
                if row.path in deleted:
                    await session.delete(row)
                    by_path.pop(row.path, None)

            for entry in entries:
                if entry["path"] in by_path:
                    continue

                if any(cls.is_under(entry["path"], path) for path in deleted):
                    continue

                await cls._create(session, entry, by_path, rows)

            for entry in entries:
                row = by_path.get(entry["path"])

                if row is not None:
                    row.description = entry["description"]

            for row in rows:
                row.depth = cls.depth_of(row.path)
                parent = by_path.get(cls.parent_path(row.path))
                row.parent_id = parent.id if parent is not None else None

            await session.commit()

            cls._log(f"synchronized {len(entries)} tags ({len(deleted)} deleted, {photos} photos updated)")

        await DatabaseService.execute(_sync)

        return await cls.get_tree()

    @classmethod
    def _validate(cls, payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        seen: set[str] = set()

        for raw in payload:
            path = cls.normalize(str(raw.get("path") or ""))

            if not path:
                raise ValueError("a tag path cannot be empty")

            if path in seen:
                raise ValueError(f"duplicate tag path: {path}")

            if cls.depth_of(path) + 1 > cls.MAX_DEPTH:
                raise ValueError(f"tag path is too deep (max {cls.MAX_DEPTH} levels): {path}")

            seen.add(path)

            description = raw.get("description")
            tag_id = raw.get("id")

            try:
                parsed_id = int(tag_id) if tag_id is not None else None
            except (TypeError, ValueError) as exception:
                raise ValueError(f"invalid tag id: {tag_id}") from exception

            entries.append({"id": parsed_id, "path": path, "description": str(description) if description else None})

        return entries

    @classmethod
    async def _apply_renames(
        cls, session, entries: list[dict[str, Any]], rows: list[Tag], by_id: dict[int, Tag], by_path: dict[str, Tag]
    ) -> None:
        for entry in entries:
            tag_id = entry["id"]
            current = by_id.get(tag_id) if tag_id is not None else None

            if current is None or current.path == entry["path"]:
                continue

            old_path = current.path
            new_path = entry["path"]

            if new_path.startswith(old_path + cls.SEPARATOR):
                raise ValueError(f"cannot move '{old_path}' into its own subtree")

            if new_path in by_path:
                raise ValueError(f"a tag already exists at '{new_path}'")

            for other in entries:
                if other is entry:
                    continue

                if other["path"].startswith(old_path + cls.SEPARATOR):
                    other["path"] = new_path + other["path"][len(old_path) :]

            await cls._rename(session, rows, by_path, old_path, new_path)

    @classmethod
    async def _rename(cls, session, rows: list[Tag], by_path: dict[str, Tag], old_path: str, new_path: str) -> None:
        prefix = old_path + cls.SEPARATOR

        for row in rows:
            if row.path == old_path:
                row.path = new_path
                row.name = cls.name_of(new_path)
            elif row.path.startswith(prefix):
                row.path = new_path + row.path[len(old_path) :]
                row.name = cls.name_of(row.path)

        by_path.clear()
        by_path.update({row.path: row for row in rows})

        await cls._rewrite_photos(session, old_path, new_path)

    @classmethod
    def _deleted_paths(
        cls, rows: list[Tag], by_id: dict[int, Tag], by_path: dict[str, Tag], entries: list[dict[str, Any]]
    ) -> set[str]:
        """Paths of the tags the payload drops, together with their descendants."""
        keep_ids = {entry["id"] for entry in entries if entry["id"] is not None and entry["id"] in by_id}
        keep_paths = {entry["path"] for entry in entries}

        deleted = {row.path for row in rows if row.id not in keep_ids and row.path not in keep_paths}

        # A deleted tag takes its whole subtree with it, even when the payload
        # still lists one of its descendants.
        changed = True

        while changed:
            changed = False

            for row in rows:
                if row.path in deleted:
                    continue

                if any(cls.is_under(row.path, path) for path in deleted):
                    deleted.add(row.path)
                    changed = True

        return deleted

    @classmethod
    async def _create(cls, session, entry: dict[str, Any], by_path: dict[str, Tag], rows: list[Tag]) -> None:
        path = entry["path"]
        segments = path.split(cls.SEPARATOR)

        for depth in range(1, len(segments) + 1):
            current = cls.SEPARATOR.join(segments[:depth])

            if current in by_path:
                continue

            parent_path = cls.SEPARATOR.join(segments[: depth - 1]) if depth > 1 else ""
            parent = by_path.get(parent_path)
            tag = Tag(
                name=segments[depth - 1],
                path=current,
                parent_id=parent.id if parent is not None else None,
                depth=depth - 1,
                description=entry["description"] if depth == len(segments) else None,
            )

            session.add(tag)
            await session.flush()

            by_path[current] = tag
            rows.append(tag)
