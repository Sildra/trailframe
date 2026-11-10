from __future__ import annotations

from datetime import datetime

import allure
import pytest

from trailframe.models.photo import Photo
from trailframe.services.rules.ast import Definition
from trailframe.services.rules.evaluator import matches
from trailframe.services.rules.schema import RuleValidationError, as_number, resolve, validate_definition


def _definition(**body) -> Definition:
    return Definition.model_validate(body)


def _add_photos(app, photos):
    async def _insert():
        from trailframe.services.core.database_service import DatabaseService

        async def _op(session):
            for photo in photos:
                session.add(photo)
            await session.commit()
            return [photo.id for photo in photos]

        return await DatabaseService.execute(_op)

    return app.db(_insert())


def _flatten(nodes):
    entries = []

    for node in nodes:
        entries.append({"id": node["id"], "path": node["path"]})
        entries.extend(_flatten(node.get("children") or []))

    return entries


def _dog_rule(tag: str = "Animals/Pet/Dog") -> dict:
    return {
        "tag": tag,
        "name": "Dogs",
        "expression": 'objects has "dog" with confidence >= 80%',
        "definition": {
            "match": "all",
            "conditions": [
                {
                    "type": "detection",
                    "label": "dog",
                    "op": "present",
                    "metrics": [{"name": "confidence", "op": "gte", "value": 80}],
                }
            ],
        },
    }


class TestSchema:
    @allure.title("Resolves typed values, including EXIF ratios and derived fields")
    def test_resolve(self):
        photo = Photo(
            path="a.jpg",
            date=datetime(2024, 5, 1),
            exif={"FNumber": "28/10", "ExifImageWidth": "1000", "ExifImageHeight": "500"},
        )

        assert as_number("1/250") == pytest.approx(0.004)
        assert resolve(photo, "exif.FNumber") == pytest.approx(2.8)
        assert resolve(photo, "width") == 1000
        assert resolve(photo, "orientation") == "landscape"
        assert resolve(photo, "date") == "2024-05-01"

    @allure.title("Rejects unknown fields, wrong operators and malformed values")
    def test_validation(self):
        with pytest.raises(RuleValidationError):
            validate_definition(_definition(conditions=[{"type": "scalar", "path": "nope", "op": "eq", "value": 1}]))

        with pytest.raises(RuleValidationError):
            validate_definition(
                _definition(conditions=[{"type": "scalar", "path": "filename", "op": "gt", "value": "a"}])
            )

        with pytest.raises(RuleValidationError):
            validate_definition(
                _definition(conditions=[{"type": "scalar", "path": "exif.ISOSpeedRatings", "op": "gt", "value": "x"}])
            )

        with pytest.raises(RuleValidationError):
            validate_definition(_definition(conditions=[]))

        with pytest.raises(RuleValidationError):
            validate_definition(
                _definition(
                    conditions=[
                        {
                            "type": "detection",
                            "label": "dog",
                            "op": "present",
                            "metrics": [{"name": "confidence", "op": "gte", "value": 120}],
                        }
                    ]
                )
            )

    @allure.title("Accepts nested all/any groups")
    def test_groups(self):
        definition = _definition(
            match="any",
            conditions=[
                {
                    "type": "group",
                    "match": "all",
                    "conditions": [{"type": "scalar", "path": "is_favorite", "op": "eq", "value": True}],
                },
                {"type": "detection", "label": "cat", "op": "present"},
            ],
        )

        assert validate_definition(definition) is definition


class TestEvaluation:
    @allure.title("Binds a label and its metrics to the same detection")
    def test_detection_binding(self):
        photo = Photo(
            path="a.jpg",
            exif={"ExifImageWidth": "1000", "ExifImageHeight": "500"},
            objects={
                "reference": {"width": 1000, "height": 500},
                "detections": [
                    {"label": "dog", "confidence": 0.95, "box": [0, 0, 10, 10], "surface": 0.0},
                    {"label": "cat", "confidence": 0.5, "box": [0, 0, 100, 100], "surface": 0.02},
                ],
            },
        )

        definition = _definition(
            conditions=[
                {
                    "type": "detection",
                    "label": "dog",
                    "op": "present",
                    "metrics": [{"name": "confidence", "op": "gte", "value": 90}],
                }
            ]
        )
        assert matches(photo, definition)

        definition = _definition(
            conditions=[
                {
                    "type": "detection",
                    "label": "cat",
                    "op": "present",
                    "metrics": [{"name": "confidence", "op": "gte", "value": 90}],
                }
            ]
        )
        assert not matches(photo, definition)

    @allure.title("Reads the stored surface instead of recomputing it from the main file")
    def test_surface_uses_stored_reference(self):
        # The main/EXIF size is 1000x500 (area 500000); the box covers 50x50. Recomputed
        # from those dimensions the surface would be 0.005, but the stored value is 0.25.
        photo = Photo(
            path="a.jpg",
            exif={"ExifImageWidth": "1000", "ExifImageHeight": "500"},
            objects={
                "reference": {"width": 200, "height": 100},
                "detections": [{"label": "dog", "confidence": 0.95, "box": [0, 0, 50, 50], "surface": 0.25}],
            },
        )

        definition = _definition(
            conditions=[
                {
                    "type": "detection",
                    "label": "dog",
                    "op": "present",
                    "metrics": [{"name": "surface", "op": "gte", "value": 20}],
                }
            ]
        )
        assert matches(photo, definition)

    @allure.title("Compares numbers, dates, booleans and lists in a typed way")
    def test_scalars(self):
        photo = Photo(
            path="a.jpg",
            filename="Sunset.jpg",
            is_favorite=True,
            date=datetime(2024, 6, 1),
            exif={"FNumber": "28/10", "ISOSpeedRatings": "400"},
            tags=["Landscape/Sky/Sunset"],
        )

        def condition(path, op, value):
            return _definition(conditions=[{"type": "scalar", "path": path, "op": op, "value": value}])

        assert matches(photo, condition("exif.FNumber", "lt", 4))
        assert matches(photo, condition("exif.ISOSpeedRatings", "gte", 400))
        assert matches(photo, condition("date", "gte", "2024-01-01"))
        assert matches(photo, condition("is_favorite", "eq", True))
        assert matches(photo, condition("filename", "contains", "sunset"))
        assert matches(photo, condition("tags", "contains", "sunset"))

    @allure.title("Combines groups with all/any")
    def test_groups(self):
        photo = Photo(path="a.jpg", is_favorite=True)

        definition = _definition(
            match="any",
            conditions=[
                {"type": "scalar", "path": "is_favorite", "op": "eq", "value": False},
                {
                    "type": "group",
                    "match": "all",
                    "conditions": [{"type": "scalar", "path": "filename", "op": "contains", "value": "a"}],
                },
            ],
        )

        # filename is None, so the inner group is false and the favorite branch is false.
        assert not matches(photo, definition)

        photo.filename = "a.jpg"
        assert matches(photo, definition)


class TestRulesApi:
    @allure.title("Serves the photo schema and the value dictionaries")
    def test_schema_and_values(self, app):
        schema = app.get("/api/rules/schema").json()

        assert {group["name"] for group in schema["groups"]} >= {"Objects", "Camera", "Place"}
        detection = next(field for group in schema["groups"] for field in group["fields"] if field["path"] == "objects")
        assert [metric["name"] for metric in detection["detection"]["metrics"]] == ["confidence", "surface"]
        assert [metric["unit"] for metric in detection["detection"]["metrics"]] == ["%", "%"]
        assert detection["detection"]["metrics"][0]["max"] == 100

        values = app.get("/api/rules/values").json()
        assert "objects" in values and "tags" in values

    @allure.title("Creates, updates, previews and deletes a rule")
    def test_rule_lifecycle(self, app):
        _add_photos(
            app,
            [
                Photo(
                    path="dog.jpg",
                    filename="dog.jpg",
                    objects={
                        "reference": {"width": 1000, "height": 500},
                        "detections": [{"label": "dog", "confidence": 0.95, "box": [0, 0, 10, 10], "surface": 0.0}],
                    },
                ),
                Photo(
                    path="cat.jpg",
                    filename="cat.jpg",
                    objects={
                        "reference": {"width": 1000, "height": 500},
                        "detections": [{"label": "cat", "confidence": 0.99, "box": [0, 0, 10, 10], "surface": 0.0}],
                    },
                ),
            ],
        )

        created = app.post("/api/rules", json=_dog_rule())
        assert created.status_code == 200, created.text
        rule = created.json()
        assert rule["tag"] == "Animals/Pet/Dog"
        assert rule["id"]

        listed = app.get("/api/rules").json()
        assert [item["id"] for item in listed] == [rule["id"]]

        preview = app.post(
            "/api/rules/preview", json={"tag": "Animals/Pet/Dog", "definition": _dog_rule()["definition"]}
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["count"] == 1
        assert preview.json()["photos"][0]["filename"] == "dog.jpg"

        updated = app.put(f"/api/rules/{rule['id']}", json={**_dog_rule(), "name": "Good dogs", "enabled": False})
        assert updated.status_code == 200, updated.text
        assert updated.json()["name"] == "Good dogs"
        assert updated.json()["enabled"] is False

        assert app.delete(f"/api/rules/{rule['id']}").status_code == 200
        assert app.get("/api/rules").json() == []

    @allure.title("A renamed tag carries its rules and a deleted tag removes them")
    def test_tag_lifecycle_carries_rules(self, app):
        created = app.post("/api/rules", json=_dog_rule()).json()
        tree = app.get("/api/tags").json()

        renamed = _flatten(tree)
        for entry in renamed:
            if entry["path"] == "Animals/Pet/Dog":
                entry["path"] = "Animals/Pet/Good Dog"

        response = app.put("/api/tags", json={"tags": renamed})
        assert response.status_code == 200, response.text

        rules = app.get("/api/rules").json()
        assert [(item["id"], item["tag"]) for item in rules] == [(created["id"], "Animals/Pet/Good Dog")]

        target = next(entry for entry in renamed if entry["path"] == "Animals/Pet/Good Dog")
        assert app.delete(f"/api/tags/{target['id']}").status_code == 200

        assert app.get("/api/rules").json() == []

    @allure.title("Applies enabled rules to the library, add-only")
    def test_apply(self, app):
        photo_id = _add_photos(
            app,
            [
                Photo(
                    path="dog.jpg",
                    filename="dog.jpg",
                    objects={
                        "reference": {"width": 1000, "height": 500},
                        "detections": [{"label": "dog", "confidence": 0.99, "box": [0, 0, 10, 10], "surface": 0.0}],
                    },
                )
            ],
        )[0]

        app.post("/api/rules", json=_dog_rule())

        applied = app.post("/api/rules/apply")
        assert applied.status_code == 200, applied.text
        assert applied.json()["changed"] == 1

        photo = app.get(f"/api/photos/{photo_id}/data").json()
        assert "Animals/Pet/Dog" in photo["tags"]
