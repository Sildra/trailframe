from __future__ import annotations

import allure
import pytest
from sqlalchemy import select

from trailframe.models.photo import Photo
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.photos.tag_service import TagConflictError, TagService


def _find(tree, path):
    """Find a node of a tree of TagNode objects."""
    for node in tree:
        if node.path == path:
            return node

        found = _find(node.children, path)

        if found is not None:
            return found

    return None


def _flatten(tree) -> list[dict]:
    """Flatten a tree of TagNode objects into the payload of the bulk editor."""
    entries: list[dict] = []

    for node in tree:
        entries.append({"id": node.id, "path": node.path, "description": node.description})
        entries.extend(_flatten(node.children))

    return entries


def _flatten_json(tree) -> list[dict]:
    """Flatten a tree of JSON nodes into the payload of the bulk editor."""
    entries: list[dict] = []

    for node in tree:
        entries.append({"id": node["id"], "path": node["path"], "description": node["description"]})
        entries.extend(_flatten_json(node["children"]))

    return entries


def _find_json(tree, path):
    """Find a node of a tree of JSON nodes."""
    for node in tree:
        if node["path"] == path:
            return node

        found = _find_json(node["children"], path)

        if found is not None:
            return found

    return None


async def _photo_tags() -> list[list[str]]:
    """The tags of every photo, in insertion order."""

    async def _read(session):
        photos = (await session.execute(select(Photo).order_by(Photo.id))).scalars().all()
        return [list(photo.tags or []) for photo in photos]

    return await DatabaseService.execute(_read)


def _add_photos(app, photos) -> list[int]:
    """Insert photos on the app's database thread."""

    async def _insert():
        async def _op(session):
            for photo in photos:
                session.add(photo)

            await session.commit()

            return [photo.id for photo in photos]

        return await DatabaseService.execute(_op)

    return app.db(_insert())


class TestTagPaths:
    @allure.title("Normalizes a tag path by trimming and dropping empty segments")
    def test_normalize(self):
        assert TagService.normalize("  Landscape / Mountain ") == "Landscape/Mountain"
        assert TagService.normalize("Landscape//Mountain") == "Landscape/Mountain"
        assert TagService.normalize("/") == ""
        assert TagService.normalize("") == ""

    @allure.title("Computes the ancestors and the parent of a path")
    def test_ancestors(self):
        assert TagService.ancestors("A/B/C") == ["A", "A/B"]
        assert TagService.parent_path("A/B/C") == "A/B"
        assert TagService.parent_path("A") == ""
        assert TagService.name_of("A/B/C") == "C"
        assert TagService.depth_of("A/B/C") == 2


class TestTagService:
    @allure.title("Seeds the default vocabulary and keeps it idempotent")
    @pytest.mark.asyncio
    async def test_seed_defaults_is_idempotent(self, db_session):
        created = await TagService.seed_defaults()
        assert created > 0

        tree = await TagService.get_tree()
        paths = {entry["path"] for entry in _flatten(tree)}

        assert "Landscape" in paths
        assert "Landscape/Mountain" in paths
        assert "Architecture/Building/Church" in paths

        assert await TagService.seed_defaults() == 0

    @allure.title("Registers a path together with its ancestors")
    @pytest.mark.asyncio
    async def test_ensure_paths_creates_ancestors(self, db_session):
        await TagService.ensure_paths(["A/B/C"])

        tree = await TagService.get_tree()

        assert _find(tree, "A") is not None
        assert _find(tree, "A/B") is not None
        assert _find(tree, "A/B/C") is not None

    @allure.title("Counts the photos of a tag and of its descendants")
    @pytest.mark.asyncio
    async def test_counts(self, db_session):
        async def _seed(session):
            session.add(Photo(path="a.jpg", filename="a.jpg", tags=["A/B"]))
            session.add(Photo(path="b.jpg", filename="b.jpg", tags=["A/B/C"]))
            session.add(Photo(path="c.jpg", filename="c.jpg", tags=["A"]))
            await session.commit()

        await DatabaseService.execute(_seed)
        await TagService.ensure_paths(["A/B", "A/B/C"])

        tree = await TagService.get_tree()
        node = _find(tree, "A")

        assert node.count == 1
        assert node.total == 3

        child = _find(tree, "A/B")
        assert child.count == 1
        assert child.total == 2

    @allure.title("Replaces the tags of a photo with the given list")
    @pytest.mark.asyncio
    async def test_set_photo_tags(self, db_session):
        async def _seed(session):
            photo = Photo(path="a.jpg", filename="a.jpg", tags=["Old"])
            session.add(photo)
            await session.commit()
            return photo.id

        photo_id = await DatabaseService.execute(_seed)
        result = await TagService.set_photo_tags(photo_id, ["New/One", "New/Two"])

        assert result == ["New/One", "New/Two"]
        assert await _photo_tags() == [["New/One", "New/Two"]]

    @allure.title("Returns None when the photo to tag does not exist")
    @pytest.mark.asyncio
    async def test_set_photo_tags_unknown_photo(self, db_session):
        assert await TagService.set_photo_tags(4242, ["A"]) is None


class TestTagSync:
    @allure.title("Renames a tag and moves its descendants and the photos carrying them")
    @pytest.mark.asyncio
    async def test_rename(self, db_session):
        async def _seed(session):
            session.add(Photo(path="a.jpg", filename="a.jpg", tags=["A/B", "A/B/C"]))
            await session.commit()

        await DatabaseService.execute(_seed)
        await TagService.ensure_paths(["A/B", "A/B/C"])

        entries = _flatten(await TagService.get_tree())

        for entry in entries:
            if entry["path"] == "A/B":
                entry["path"] = "A/X"

        await TagService.sync(entries)

        tree = await TagService.get_tree()
        assert _find(tree, "A/B") is None
        assert _find(tree, "A/X") is not None
        assert _find(tree, "A/X/C") is not None

        assert await _photo_tags() == [["A/X", "A/X/C"]]

    @allure.title("Creates the tags missing from the payload")
    @pytest.mark.asyncio
    async def test_create(self, db_session):
        await TagService.sync([{"path": "New/Leaf"}])

        tree = await TagService.get_tree()
        assert _find(tree, "New") is not None
        assert _find(tree, "New/Leaf") is not None

    @allure.title("Deletes the tags missing from the payload, with their descendants")
    @pytest.mark.asyncio
    async def test_cascade_delete(self, db_session):
        async def _seed(session):
            session.add(Photo(path="a.jpg", filename="a.jpg", tags=["A/B", "A/B/C"]))
            await session.commit()

        await DatabaseService.execute(_seed)
        await TagService.ensure_paths(["A/B", "A/B/C"])

        entries = [entry for entry in _flatten(await TagService.get_tree()) if entry["path"] != "A/B"]

        await TagService.sync(entries)

        tree = await TagService.get_tree()
        assert _find(tree, "A/B") is None
        assert _find(tree, "A/B/C") is None

        assert await _photo_tags() == [[]]

    @allure.title("A descendant kept in the payload dies with its deleted parent")
    @pytest.mark.asyncio
    async def test_kept_descendant_is_deleted(self, db_session):
        await TagService.ensure_paths(["A/B", "A/B/C"])

        entries = [entry for entry in _flatten(await TagService.get_tree()) if entry["path"] != "A"]

        await TagService.sync(entries)

        tree = await TagService.get_tree()
        assert _find(tree, "A") is None
        assert _find(tree, "A/B") is None
        assert _find(tree, "A/B/C") is None

    @allure.title("Rejects a payload with duplicate paths")
    @pytest.mark.asyncio
    async def test_rejects_duplicates(self, db_session):
        with pytest.raises(ValueError):
            await TagService.sync([{"path": "A"}, {"path": "A"}])

    @allure.title("Rejects an empty path")
    @pytest.mark.asyncio
    async def test_rejects_empty_path(self, db_session):
        with pytest.raises(ValueError):
            await TagService.sync([{"path": "   "}])

    @allure.title("Rejects a path deeper than the limit")
    @pytest.mark.asyncio
    async def test_rejects_deep_path(self, db_session):
        with pytest.raises(ValueError):
            await TagService.sync([{"path": "/".join(["x"] * (TagService.MAX_DEPTH + 1))}])

    @allure.title("Rejects moving a tag into its own subtree")
    @pytest.mark.asyncio
    async def test_rejects_move_into_own_subtree(self, db_session):
        await TagService.ensure_paths(["A/B"])

        entries = _flatten(await TagService.get_tree())

        for entry in entries:
            if entry["path"] == "A":
                entry["path"] = "A/B/A"

        with pytest.raises(ValueError):
            await TagService.sync(entries)


class TestTagCreate:
    @allure.title("Adds a single tag and creates its missing ancestors")
    @pytest.mark.asyncio
    async def test_create_adds_the_ancestors(self, db_session):
        tree = await TagService.create("A/B/C", "a description")

        assert _find(tree, "A") is not None
        assert _find(tree, "A/B") is not None

        node = _find(tree, "A/B/C")
        assert node is not None
        assert node.description == "a description"

    @allure.title("Keeps the rest of the vocabulary when a tag is added")
    @pytest.mark.asyncio
    async def test_create_keeps_the_other_tags(self, db_session):
        await TagService.create("A")
        await TagService.create("B")

        tree = await TagService.create("A/C")

        paths = {entry["path"] for entry in _flatten(tree)}
        assert paths == {"A", "A/C", "B"}

    @allure.title("Refuses a tag path that is already taken")
    @pytest.mark.asyncio
    async def test_create_refuses_a_duplicate(self, db_session):
        await TagService.create("A")

        with pytest.raises(TagConflictError):
            await TagService.create("A")

    @allure.title("Refuses an empty or too deep path")
    @pytest.mark.asyncio
    async def test_create_refuses_an_invalid_path(self, db_session):
        with pytest.raises(ValueError):
            await TagService.create("   ")

        with pytest.raises(ValueError):
            await TagService.create("/".join(["x"] * (TagService.MAX_DEPTH + 1)))


class TestTagApi:
    @allure.title("Lists the tag tree")
    def test_list_tags(self, app):
        response = app.get("/api/tags")
        assert response.status_code == 200

        paths = {entry["path"] for entry in _flatten_json(response.json())}
        assert "Landscape" in paths

    @allure.title("Saves the whole vocabulary in one request")
    def test_update_tags(self, app):
        entries = _flatten_json(app.get("/api/tags").json())
        entries.append({"id": None, "path": "Brand/New", "description": "added by the editor"})

        response = app.put("/api/tags", json={"tags": entries})
        assert response.status_code == 200

        node = _find_json(response.json(), "Brand/New")
        assert node is not None
        assert node["description"] == "added by the editor"

    @allure.title("Rejects an invalid vocabulary with a 400")
    def test_update_tags_invalid(self, app):
        response = app.put("/api/tags", json={"tags": [{"path": "A"}, {"path": "A"}]})
        assert response.status_code == 400

    @allure.title("Deletes a tag and its descendants")
    def test_delete_tag(self, app):
        node = _find_json(app.get("/api/tags").json(), "Quality")

        assert node is not None

        response = app.delete(f"/api/tags/{node['id']}")
        assert response.status_code == 200
        assert response.json()["deleted"] is True

        assert _find_json(app.get("/api/tags").json(), "Quality") is None
        assert _find_json(app.get("/api/tags").json(), "Quality/Macro") is None

    @allure.title("Returns a 404 for an unknown tag")
    def test_delete_unknown_tag(self, app):
        assert app.delete("/api/tags/999999").status_code == 404

    @allure.title("Adds a single tag with its missing ancestors")
    def test_create_tag(self, app):
        response = app.post("/api/tags", json={"path": "Brand/New", "description": "quick add"})
        assert response.status_code == 200

        node = _find_json(response.json(), "Brand/New")
        assert node is not None
        assert node["description"] == "quick add"

        tree = app.get("/api/tags").json()
        assert _find_json(tree, "Brand") is not None
        assert _find_json(tree, "Landscape") is not None

    @allure.title("Returns a 409 when the tag path is already taken")
    def test_create_tag_conflict(self, app):
        assert app.post("/api/tags", json={"path": "Landscape"}).status_code == 409

    @allure.title("Returns a 400 for an empty tag path")
    def test_create_tag_invalid(self, app):
        assert app.post("/api/tags", json={"path": "   "}).status_code == 400


class TestPhotoTagApi:
    @allure.title("Filters the photos by tag, including the descendants")
    def test_filter_photos(self, app):
        _add_photos(
            app,
            [
                Photo(path="a.jpg", filename="a.jpg", tags=["A/B"]),
                Photo(path="b.jpg", filename="b.jpg", tags=["A"]),
                Photo(path="c.jpg", filename="c.jpg", tags=["Other"]),
            ],
        )

        assert app.get("/api/photos/ids", params={"tags": "A"}).json() == [1, 2]
        assert app.get("/api/photos/ids", params={"tags": "A/B"}).json() == [1]
        assert app.get("/api/photos/ids", params={"tags": "A/B", "include_descendants": "false"}).json() == [1]
        assert app.get("/api/photos/ids", params={"tags": ["A", "Other"]}).json() == [1, 2, 3]
        assert app.get("/api/photos/ids", params={"tags": ["A", "Other"], "tags_mode": "all"}).json() == []

    @allure.title("Sets the tags of a photo in one request")
    def test_set_photo_tags(self, app):
        photo_id = _add_photos(app, [Photo(path="a.jpg", filename="a.jpg")])[0]

        response = app.put(f"/api/photos/{photo_id}/tags", json={"tags": ["A/B", "C"]})
        assert response.status_code == 200
        assert response.json()["tags"] == ["A/B", "C"]

    @allure.title("Returns a 404 when tagging an unknown photo")
    def test_set_photo_tags_unknown(self, app):
        assert app.put("/api/photos/999999/tags", json={"tags": ["A"]}).status_code == 404
