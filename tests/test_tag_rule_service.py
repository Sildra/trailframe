from __future__ import annotations

from datetime import datetime

import allure
import pytest
from sqlalchemy import select

from trailframe.models.photo import Photo
from trailframe.models.tag_rule import TagRule
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.photos.tag_rule_service import TagRuleService, TagRuleValidationError
from trailframe.services.photos.tag_service import TagService
from trailframe.services.pipelines.item import Item
from trailframe.services.scanners.rules_scanner import RulesScanner


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


async def _photo_tags(photo_id: int) -> list[str]:
    async def _read(session):
        photo = (await session.execute(select(Photo).where(Photo.id == photo_id))).scalar_one()
        return list(photo.tags or [])

    return await DatabaseService.execute(_read)


def _dog_rule(name: str = "Dogs", tags: list[str] | None = None) -> dict:
    """The example rule: a confident, large enough dog detection."""
    return {
        "name": name,
        "enabled": True,
        "priority": 10,
        "conditions": {
            "operator": "and",
            "rules": [
                {
                    "field": "objects",
                    "match_label": "dog",
                    "constraints": {"confidence": {"gte": 0.8}, "surface": {"gte": 0.1}},
                }
            ],
        },
        "tags": tags or ["Animals/Pet/Dog"],
    }


def _rule(rule: dict) -> TagRule:
    """A validated, in-memory TagRule (never persisted)."""
    return TagRule(**TagRuleService.validate(rule))


class TestRuleFields:
    @allure.title("Exposes the metadata catalog the builder renders")
    def test_fields_catalog(self):
        fields = TagRuleService.fields()
        by_field = {entry["field"]: entry for entry in fields}

        assert "objects" in by_field
        assert "exif.Make" in by_field
        assert "date" in by_field
        assert "is_favorite" in by_field
        assert "scores.brisque" in by_field

        objects = by_field["objects"]
        assert objects["kind"] == "objects"
        assert set(objects["metrics"]) == {"confidence", "surface"}
        assert "dog" in objects["suggestions"]
        assert any(op["op"] == "present" for op in objects["operators"])

    @allure.title("Offers the numeric operators on a number field")
    def test_number_field_operators(self):
        fields = {entry["field"]: entry for entry in TagRuleService.fields()}
        ops = {op["op"] for op in fields["file_size"]["operators"]}

        assert {"gt", "gte", "lt", "lte", "eq", "neq"} <= ops


class TestRuleValidation:
    @allure.title("Normalizes a valid rule")
    def test_validate_normalizes(self):
        clean = TagRuleService.validate(_dog_rule())

        assert clean["name"] == "Dogs"
        assert clean["priority"] == 10
        assert clean["conditions"]["operator"] == "and"
        assert clean["conditions"]["rules"][0]["match_label"] == "dog"
        assert clean["tags"] == ["Animals/Pet/Dog"]

    @allure.title("Rejects a rule without a name")
    def test_validate_requires_name(self):
        with pytest.raises(TagRuleValidationError):
            TagRuleService.validate({**_dog_rule(), "name": "  "})

    @allure.title("Rejects a rule without conditions")
    def test_validate_requires_conditions(self):
        with pytest.raises(TagRuleValidationError):
            TagRuleService.validate({**_dog_rule(), "conditions": {"operator": "and", "rules": []}})

    @allure.title("Rejects a rule without tags")
    def test_validate_requires_tags(self):
        with pytest.raises(TagRuleValidationError):
            TagRuleService.validate({**_dog_rule(), "tags": []})

    @allure.title("Rejects an unknown metadata field")
    def test_validate_unknown_field(self):
        rule = _dog_rule()
        rule["conditions"]["rules"][0]["field"] = "nonsense"

        with pytest.raises(TagRuleValidationError):
            TagRuleService.validate(rule)

    @allure.title("Rejects a numeric constraint that is not a number")
    def test_validate_numeric_constraint(self):
        rule = _dog_rule()
        rule["conditions"]["rules"][0]["constraints"]["confidence"] = {"gte": "high"}

        with pytest.raises(TagRuleValidationError):
            TagRuleService.validate(rule)

    @allure.title("Trims and lowercases the matched object label")
    def test_validate_label_lowercased(self):
        rule = _dog_rule()
        rule["conditions"]["rules"][0]["match_label"] = "  Dog "

        clean = TagRuleService.validate(rule)

        assert clean["conditions"]["rules"][0]["match_label"] == "dog"


class TestRuleMatching:
    def _photo(self, **overrides) -> Photo:
        values = {"path": "p.jpg", "filename": "p.jpg"}
        values.update(overrides)

        return Photo(**values)

    @allure.title("Matches a confident and large enough object")
    def test_matches_objects(self):
        photo = self._photo(
            exif={"ExifImageWidth": "1000", "ExifImageHeight": "1000"},
            objects=[{"label": "dog", "confidence": 0.91, "box": [0, 0, 400, 300]}],
        )
        rule = _rule(_dog_rule())

        assert TagRuleService.matches(photo, rule) is True
        assert TagRuleService.matching_tags(photo, rule) == ["Animals/Pet/Dog"]

    @allure.title("Rejects a low confidence detection")
    def test_rejects_low_confidence(self):
        photo = self._photo(
            exif={"ExifImageWidth": "1000", "ExifImageHeight": "1000"},
            objects=[{"label": "dog", "confidence": 0.5, "box": [0, 0, 400, 300]}],
        )

        assert TagRuleService.matches(photo, _rule(_dog_rule())) is False

    @allure.title("Rejects a detection covering too little of the frame")
    def test_rejects_small_surface(self):
        photo = self._photo(
            exif={"ExifImageWidth": "1000", "ExifImageHeight": "1000"},
            objects=[{"label": "dog", "confidence": 0.95, "box": [0, 0, 100, 100]}],
        )

        assert TagRuleService.matches(photo, _rule(_dog_rule())) is False

    @allure.title("Computes the surface as a share of the image area")
    def test_surface_share(self):
        photo = self._photo(
            exif={"ExifImageWidth": "2000", "ExifImageHeight": "1000"},
            objects=[{"label": "dog", "confidence": 0.95, "box": [0, 0, 1000, 500]}],
        )
        detections = TagRuleService._detections(photo, "dog")

        # 1000 x 500 = 500 000 px out of 2 000 x 1 000 = 2 000 000 px.
        assert detections[0]["surface"] == 0.25

    @allure.title("Swaps the axes for a rotated EXIF orientation")
    def test_orientation_swaps_size(self):
        photo = self._photo(exif={"ExifImageWidth": "1000", "ExifImageHeight": "2000", "Orientation": "6"})

        assert TagRuleService.image_size(photo) == (2000, 1000)

    @allure.title("Matches an EXIF text field")
    def test_matches_exif(self):
        photo = self._photo(exif={"Make": "Canon"})
        rule = _rule(
            {
                "name": "Canon",
                "conditions": {
                    "operator": "and",
                    "rules": [{"field": "exif.Make", "operator": "eq", "value": "canon"}],
                },
                "tags": ["Camera/Canon"],
            }
        )

        assert TagRuleService.matches(photo, rule) is True

    @allure.title("Combines conditions with 'or'")
    def test_or_operator(self):
        photo = self._photo(is_favorite=True)
        rule = _rule(
            {
                "name": "Picks or Canon",
                "conditions": {
                    "operator": "or",
                    "rules": [
                        {"field": "exif.Make", "operator": "eq", "value": "Canon"},
                        {"field": "is_favorite", "operator": "eq", "value": True},
                    ],
                },
                "tags": ["Best"],
            }
        )

        assert TagRuleService.matches(photo, rule) is True

    @allure.title("Matches a capture date range")
    def test_matches_date_range(self):
        photo = self._photo(date=datetime(2024, 6, 15, 12, 0, 0))
        rule = _rule(
            {
                "name": "Summer 2024",
                "conditions": {
                    "operator": "and",
                    "rules": [
                        {"field": "date", "operator": "gte", "value": "2024-06-01"},
                        {"field": "date", "operator": "lte", "value": "2024-08-31"},
                    ],
                },
                "tags": ["Activity/Travel"],
            }
        )

        assert TagRuleService.matches(photo, rule) is True

    @allure.title("Matches on an existing tag")
    def test_matches_existing_tag(self):
        photo = self._photo(tags=["Landscape/Mountain"])
        rule = _rule(
            {
                "name": "Has a mountain tag",
                "conditions": {
                    "operator": "and",
                    "rules": [{"field": "tags", "operator": "contains", "value": "Landscape/Mountain"}],
                },
                "tags": ["Landscape"],
            }
        )

        assert TagRuleService.matches(photo, rule) is True

    @allure.title("Matches a present object without constraints")
    def test_matches_present_object(self):
        photo = self._photo(objects=[{"label": "person", "confidence": 0.4, "box": [0, 0, 10, 10]}])
        rule = _rule(
            {
                "name": "Any person",
                "conditions": {"operator": "and", "rules": [{"field": "objects", "match_label": "person"}]},
                "tags": ["People"],
            }
        )

        assert TagRuleService.matches(photo, rule) is True


class TestRuleService:
    @allure.title("Creates a rule and keeps the in-memory cache in sync")
    @pytest.mark.asyncio
    async def test_create_refreshes_cache(self, app):
        created = app.db(_create_rule(_dog_rule()))

        assert created["id"] is not None
        assert [rule.name for rule in TagRuleService.cached_rules()] == ["Dogs"]

    @allure.title("Returns the rules ordered by priority")
    @pytest.mark.asyncio
    async def test_list_orders_by_priority(self, app):
        app.db(_create_rule(_dog_rule("Low", tags=["A"]), priority=1))
        app.db(_create_rule(_dog_rule("High", tags=["B"]), priority=50))

        rules = app.db(_list_rules())

        assert [rule["name"] for rule in rules] == ["High", "Low"]

    @allure.title("Updates a rule")
    @pytest.mark.asyncio
    async def test_update_rule(self, app):
        created = app.db(_create_rule(_dog_rule()))

        payload = _dog_rule("Renamed", tags=["Animals/Pet/Cat"])
        payload["enabled"] = False
        updated = app.db(_update_rule(created["id"], payload))

        assert updated["name"] == "Renamed"
        assert updated["tags"] == ["Animals/Pet/Cat"]
        assert updated["enabled"] is False
        assert TagRuleService.cached_rules() == []

    @allure.title("Deletes a rule")
    @pytest.mark.asyncio
    async def test_delete_rule(self, app):
        created = app.db(_create_rule(_dog_rule()))

        assert app.db(_delete_rule(created["id"])) is True
        assert app.db(_get_rule(created["id"])) is None
        assert TagRuleService.cached_rules() == []

    @allure.title("Skips a disabled rule when assigning tags")
    @pytest.mark.asyncio
    async def test_disabled_rule_is_skipped(self, app):
        photo = Photo(
            path="dog.jpg",
            filename="dog.jpg",
            exif={"ExifImageWidth": "1000", "ExifImageHeight": "1000"},
            objects=[{"label": "dog", "confidence": 0.9, "box": [0, 0, 400, 300]}],
        )
        app.db(_insert_photos([photo]))

        payload = _dog_rule()
        payload["enabled"] = False
        app.db(_create_rule(payload))

        assert TagRuleService.tags_for_photo(photo) == []


class TestRuleApi:
    @allure.title("Exposes the field catalog")
    def test_fields_endpoint(self, app):
        response = app.get("/api/tag-rules/fields")

        assert response.status_code == 200
        fields = {entry["field"] for entry in response.json()}
        assert "objects" in fields

    @allure.title("Creates, lists, updates and deletes a rule")
    def test_crud_round_trip(self, app):
        created = app.post("/api/tag-rules", json=_dog_rule())
        assert created.status_code == 200
        rule_id = created.json()["id"]

        listed = app.get("/api/tag-rules")
        assert [rule["name"] for rule in listed.json()] == ["Dogs"]

        fetched = app.get(f"/api/tag-rules/{rule_id}")
        assert fetched.json()["tags"] == ["Animals/Pet/Dog"]

        payload = _dog_rule("Cats", tags=["Animals/Pet/Cat"])
        updated = app.put(f"/api/tag-rules/{rule_id}", json=payload)
        assert updated.json()["name"] == "Cats"

        deleted = app.delete(f"/api/tag-rules/{rule_id}")
        assert deleted.status_code == 200
        assert app.get(f"/api/tag-rules/{rule_id}").status_code == 404

    @allure.title("Rejects a malformed rule")
    def test_create_rejects_invalid(self, app):
        payload = _dog_rule()
        payload["name"] = ""

        assert app.post("/api/tag-rules", json=payload).status_code == 400

    @allure.title("Tests a draft rule against the existing photos")
    def test_test_endpoint(self, app):
        app.db(
            _insert_photos(
                [
                    Photo(
                        path="dog.jpg",
                        filename="dog.jpg",
                        exif={"ExifImageWidth": "1000", "ExifImageHeight": "1000"},
                        objects=[{"label": "dog", "confidence": 0.9, "box": [0, 0, 400, 300]}],
                    ),
                    Photo(
                        path="cat.jpg",
                        filename="cat.jpg",
                        objects=[{"label": "cat", "confidence": 0.9, "box": [0, 0, 400, 300]}],
                    ),
                ]
            )
        )

        response = app.post("/api/tag-rules/test", json={"rule": _dog_rule(), "limit": 10})

        assert response.status_code == 200
        matches = response.json()
        assert len(matches) == 1
        assert matches[0]["filename"] == "dog.jpg"
        assert matches[0]["tags"] == ["Animals/Pet/Dog"]

    @allure.title("Returns 404 when testing against an unknown rule is not needed and the rule is invalid")
    def test_test_endpoint_rejects_invalid(self, app):
        payload = _dog_rule()
        payload["tags"] = []

        assert app.post("/api/tag-rules/test", json={"rule": payload, "limit": 10}).status_code == 400

    @allure.title("Returns 404 for an unknown rule")
    def test_unknown_rule(self, app):
        assert app.get("/api/tag-rules/999").status_code == 404
        assert app.delete("/api/tag-rules/999").status_code == 404

    @allure.title("Applies the rules to the photos already in the library")
    def test_apply_endpoint(self, app):
        app.db(
            _insert_photos(
                [
                    Photo(
                        path="dog.jpg",
                        filename="dog.jpg",
                        exif={"ExifImageWidth": "1000", "ExifImageHeight": "1000"},
                        objects=[{"label": "dog", "confidence": 0.9, "box": [0, 0, 400, 300]}],
                    ),
                    Photo(
                        path="cat.jpg",
                        filename="cat.jpg",
                        objects=[{"label": "cat", "confidence": 0.9, "box": [0, 0, 400, 300]}],
                    ),
                ]
            )
        )
        app.db(_create_rule(_dog_rule()))

        response = app.post("/api/tag-rules/apply")

        assert response.status_code == 200
        body = response.json()
        assert body["photos"] == 2
        assert body["changed"] == 1
        assert body["added"] == 1

    @allure.title("Does not remove a tag when applying the rules")
    def test_apply_is_add_only(self, app):
        app.db(
            _insert_photos(
                [
                    Photo(
                        path="dog.jpg",
                        filename="dog.jpg",
                        tags=["Landscape/Mountain"],
                        exif={"ExifImageWidth": "1000", "ExifImageHeight": "1000"},
                        objects=[{"label": "dog", "confidence": 0.9, "box": [0, 0, 400, 300]}],
                    )
                ]
            )
        )
        app.db(_create_rule(_dog_rule()))

        app.post("/api/tag-rules/apply")

        tags = app.db(_read_tags())

        assert "Landscape/Mountain" in tags
        assert "Animals/Pet/Dog" in tags

    @allure.title("Registers the rule tags in the vocabulary")
    def test_apply_registers_the_vocabulary(self, app):
        app.db(
            _insert_photos(
                [
                    Photo(
                        path="dog.jpg",
                        filename="dog.jpg",
                        exif={"ExifImageWidth": "1000", "ExifImageHeight": "1000"},
                        objects=[{"label": "dog", "confidence": 0.9, "box": [0, 0, 400, 300]}],
                    )
                ]
            )
        )
        app.db(_create_rule(_dog_rule()))

        app.post("/api/tag-rules/apply")

        tree = app.db(_read_tree())

        assert _find(tree, "Animals/Pet/Dog") is not None
        assert _find(tree, "Animals/Pet") is not None


class TestRulesScanner:
    @allure.title("Adds the rule tags to a matching photo and registers the vocabulary")
    @pytest.mark.asyncio
    async def test_scanner_adds_tags(self, app):
        photo = Photo(
            path="dog.jpg",
            filename="dog.jpg",
            exif={"ExifImageWidth": "1000", "ExifImageHeight": "1000"},
            objects=[{"label": "dog", "confidence": 0.9, "box": [0, 0, 400, 300]}],
        )
        app.db(_insert_photos([photo]))
        app.db(_create_rule(_dog_rule()))

        scanner = RulesScanner()
        item = Item(photo)

        assert scanner.accept(item) is True
        assert await scanner.executePhoto(item) is True
        assert "Rules" in photo.scanners

        tree = await TagService.get_tree()
        assert _find(tree, "Animals/Pet/Dog") is not None

    @allure.title("Leaves a non-matching photo's tags untouched")
    @pytest.mark.asyncio
    async def test_scanner_skips_non_matching(self, app):
        photo = Photo(
            path="cat.jpg", filename="cat.jpg", objects=[{"label": "cat", "confidence": 0.9, "box": [0, 0, 10, 10]}]
        )
        app.db(_insert_photos([photo]))
        app.db(_create_rule(_dog_rule()))

        scanner = RulesScanner()
        item = Item(photo)

        assert await scanner.executePhoto(item) is False
        assert photo.tags == []

    @allure.title("Never removes a tag the user set by hand")
    @pytest.mark.asyncio
    async def test_scanner_is_add_only(self, app):
        photo = Photo(
            path="dog.jpg",
            filename="dog.jpg",
            tags=["Landscape/Mountain"],
            exif={"ExifImageWidth": "1000", "ExifImageHeight": "1000"},
            objects=[{"label": "dog", "confidence": 0.9, "box": [0, 0, 400, 300]}],
        )
        app.db(_insert_photos([photo]))
        app.db(_create_rule(_dog_rule()))

        item = Item(photo)

        await RulesScanner().executePhoto(item)

        assert "Landscape/Mountain" in photo.tags
        assert "Animals/Pet/Dog" in photo.tags

    @allure.title("Does not run twice on an already processed photo")
    @pytest.mark.asyncio
    async def test_scanner_runs_once(self, app):
        photo = Photo(
            path="dog.jpg",
            filename="dog.jpg",
            scanners=["Rules"],
            exif={"ExifImageWidth": "1000", "ExifImageHeight": "1000"},
            objects=[{"label": "dog", "confidence": 0.9, "box": [0, 0, 400, 300]}],
        )

        assert RulesScanner().accept(Item(photo)) is False


def _find(tree, path):
    for node in tree:
        if getattr(node, "path", None) == path:
            return node

        found = _find(getattr(node, "children", []), path)

        if found is not None:
            return found

    return None


def _insert_photos(photos):
    async def _op():
        async def _job(session):
            for photo in photos:
                session.add(photo)

            await session.commit()

            return [photo.id for photo in photos]

        return await DatabaseService.execute(_job)

    return _op()


def _create_rule(rule, priority=None):
    if priority is not None:
        rule = {**rule, "priority": priority}

    async def _op():
        created = await TagRuleService.create(rule)
        return {"id": created.id, "name": created.name}

    return _op()


def _list_rules():
    async def _op():
        return [
            {"id": rule.id, "name": rule.name, "priority": rule.priority, "tags": list(rule.tags or [])}
            for rule in await TagRuleService.list()
        ]

    return _op()


def _update_rule(rule_id, rule):
    async def _op():
        updated = await TagRuleService.update(rule_id, rule)
        return {"id": updated.id, "name": updated.name, "enabled": updated.enabled, "tags": list(updated.tags or [])}

    return _op()


def _get_rule(rule_id):
    async def _op():
        rule = await TagRuleService.get(rule_id)
        return None if rule is None else {"id": rule.id}

    return _op()


def _delete_rule(rule_id):
    async def _op():
        return await TagRuleService.delete(rule_id)

    return _op()


def _read_tags():
    async def _op():
        async def _job(session):
            photo = (await session.execute(select(Photo).where(Photo.path == "dog.jpg"))).scalar_one()

            return list(photo.tags or [])

        return await DatabaseService.execute(_job)

    return _op()


def _read_tree():
    async def _op():
        return await TagService.get_tree()

    return _op()
