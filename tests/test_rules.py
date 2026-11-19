from __future__ import annotations

from datetime import datetime

import allure
import pytest

from trailframe.models.photo import Photo
from trailframe.services.rules.ast import Definition
from trailframe.services.rules.evaluator import matches
from trailframe.services.rules.metadata import MISSING
from trailframe.services.rules.rule_service import RuleService
from trailframe.services.rules.schema import RuleValidationError, as_number, resolve, validate_definition


def _definition(**body) -> Definition:
    return Definition.model_validate(body)


def _element(key, op, value=None):
    return {"type": "element", "key": key, "op": op, "value": value}


def _collection(path="objects", quantifier="any", *conditions):
    body = conditions[0] if len(conditions) == 1 else {"type": "group", "match": "all", "conditions": list(conditions)}

    return {"type": "collection", "path": path, "quantifier": quantifier, "condition": body}


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
        "expression": 'objects[label = "dog" and confidence >= 80%] has any',
        "definition": {
            "match": "all",
            "conditions": [
                _collection("objects", "any", _element("label", "eq", "dog"), _element("confidence", "gte", 0.8))
            ],
        },
    }


def _detections(label: str, confidence: float = 0.9, surface: float = 0.1) -> dict:
    return {
        "reference": {"width": 1000, "height": 500},
        "detections": [{"label": label, "confidence": confidence, "box": [0, 0, 10, 10], "surface": surface}],
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

    @allure.title("Resolves a selected list entry and misses when it is absent or duplicated")
    def test_resolve_selected_entry(self):
        photo = Photo(path="a.jpg", processing=[{"step": "tilt", "meta": {"applied": False, "crop_mode": "none"}}])

        assert resolve(photo, "processing.tilt.applied") is False
        assert resolve(photo, "processing.tilt.crop_mode") == "none"

        photo.processing = [{"step": "rescale", "meta": {}}]
        assert resolve(photo, "processing.tilt.applied") is MISSING

        photo.processing = [{"step": "tilt", "meta": {"applied": True}}, {"step": "tilt", "meta": {"applied": False}}]
        assert resolve(photo, "processing.tilt.applied") is MISSING

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

    @allure.title("Validates collection paths, element keys, operators and ranges")
    def test_collection_validation(self):
        with pytest.raises(RuleValidationError):
            validate_definition(_definition(conditions=[_collection("nope", "any", _element("label", "eq", "dog"))]))

        with pytest.raises(RuleValidationError):
            validate_definition(
                _definition(conditions=[_collection("objects", "any", _element("colour", "eq", "red"))])
            )

        with pytest.raises(RuleValidationError):
            validate_definition(
                _definition(conditions=[_collection("objects", "any", _element("label", "gte", "dog"))])
            )

        with pytest.raises(RuleValidationError):
            validate_definition(
                _definition(conditions=[_collection("objects", "any", _element("confidence", "gte", 1.2))])
            )

        # A bare `80` (the `%` was forgotten) is out of the 0..1 range.
        with pytest.raises(RuleValidationError):
            validate_definition(
                _definition(conditions=[_collection("objects", "any", _element("confidence", "gte", 80))])
            )

        with pytest.raises(ValueError):
            validate_definition(
                _definition(conditions=[_collection("objects", "some", _element("label", "eq", "dog"))])
            )

        with pytest.raises(RuleValidationError):
            validate_definition(_definition(conditions=[_element("label", "eq", "dog")]))

        with pytest.raises(RuleValidationError):
            validate_definition(
                _definition(
                    conditions=[
                        _collection("objects", "any", _collection("processing", "any", _element("step", "eq", "tilt")))
                    ]
                )
            )

    @allure.title("Accepts nested all/any groups and a full element expression")
    def test_groups(self):
        definition = _definition(
            match="any",
            conditions=[
                {
                    "type": "group",
                    "match": "all",
                    "conditions": [{"type": "scalar", "path": "is_favorite", "op": "eq", "value": True}],
                },
                _collection(
                    "objects",
                    "one",
                    {
                        "type": "group",
                        "match": "any",
                        "conditions": [
                            {
                                "type": "group",
                                "match": "all",
                                "conditions": [_element("confidence", "gt", 0.8), _element("surface", "gt", 0.1)],
                            },
                            {
                                "type": "group",
                                "match": "all",
                                "conditions": [_element("confidence", "gt", 0.9), _element("surface", "gt", 0.07)],
                            },
                        ],
                    },
                ),
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

        dog = _definition(
            conditions=[
                _collection("objects", "any", _element("label", "eq", "dog"), _element("confidence", "gte", 0.9))
            ]
        )
        cat = _definition(
            conditions=[
                _collection("objects", "any", _element("label", "eq", "cat"), _element("confidence", "gte", 0.9))
            ]
        )

        assert matches(photo, dog)
        assert not matches(photo, cat)

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
            conditions=[_collection("objects", "any", _element("label", "eq", "dog"), _element("surface", "gte", 0.2))]
        )

        assert matches(photo, definition)

    @allure.title("Applies any, none, one and all with their empty-collection rules")
    def test_quantifiers(self):
        photo = Photo(
            path="a.jpg",
            objects={
                "detections": [
                    {"label": "dog", "confidence": 0.95, "surface": 0.2},
                    {"label": "dog", "confidence": 0.6, "surface": 0.05},
                ]
            },
        )
        empty = Photo(path="b.jpg")

        def dog(quantifier):
            return _definition(conditions=[_collection("objects", quantifier, _element("label", "eq", "dog"))])

        assert matches(photo, dog("any"))
        assert matches(photo, dog("none")) is False
        assert matches(photo, dog("one")) is False
        assert matches(photo, dog("all"))

        assert matches(empty, dog("any")) is False
        assert matches(empty, dog("none"))
        assert matches(empty, dog("one")) is False
        assert matches(empty, dog("all"))

        one = _definition(
            conditions=[
                _collection("objects", "one", _element("label", "eq", "dog"), _element("confidence", "gte", 0.9))
            ]
        )
        assert matches(photo, one)

    @allure.title("Filters processing steps by their keys")
    def test_processing_collection(self):
        photo = Photo(path="a.jpg", processing=[{"step": "tilt", "meta": {"applied": True}}, {"step": "rescale"}])

        applied = _definition(
            conditions=[
                _collection("processing", "any", _element("step", "eq", "tilt"), _element("meta.applied", "eq", True))
            ]
        )
        skipped = _definition(
            conditions=[
                _collection("processing", "any", _element("step", "eq", "tilt"), _element("meta.applied", "eq", False))
            ]
        )
        scalar = _definition(
            conditions=[{"type": "scalar", "path": "processing.tilt.applied", "op": "eq", "value": True}]
        )

        assert matches(photo, applied)
        assert not matches(photo, skipped)
        assert matches(photo, scalar)

        photo.processing = [{"step": "rescale"}]
        assert not matches(photo, applied)
        assert not matches(photo, scalar)

    @allure.title("Groups element constraints with and/or/not")
    def test_element_groups(self):
        photo = Photo(
            path="a.jpg",
            objects={
                "detections": [
                    {"label": "dog", "confidence": 0.85, "surface": 0.15},
                    {"label": "dog", "confidence": 0.95, "surface": 0.03},
                ]
            },
        )

        definition = _definition(
            conditions=[
                _collection(
                    "objects",
                    "one",
                    {
                        "type": "group",
                        "match": "any",
                        "conditions": [
                            {
                                "type": "group",
                                "match": "all",
                                "conditions": [_element("confidence", "gt", 0.8), _element("surface", "gt", 0.1)],
                            },
                            {
                                "type": "group",
                                "match": "all",
                                "conditions": [_element("confidence", "gt", 0.9), _element("surface", "gt", 0.04)],
                            },
                        ],
                    },
                )
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

        assert {group["name"] for group in schema["groups"]} >= {"Camera", "Place", "Processing"}
        assert {collection["path"] for collection in schema["collections"]} >= {"objects", "processing", "alternatives"}
        assert [quantifier["name"] for quantifier in schema["quantifiers"]] == ["any", "none", "one", "all"]

        objects = next(collection for collection in schema["collections"] if collection["path"] == "objects")
        assert [element["key"] for element in objects["elements"]] == ["label", "confidence", "surface"]
        confidence = next(element for element in objects["elements"] if element["key"] == "confidence")
        assert confidence["unit"] == "%"
        assert confidence["max"] == 1.0

        fields = {field["path"] for group in schema["groups"] for field in group["fields"]}
        assert {"processing.tilt.applied", "processing.tilt.crop_mode"} <= fields

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
        assert rule["id"] in [item["id"] for item in listed]

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
        assert rule["id"] not in [item["id"] for item in app.get("/api/rules").json()]

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
        assert (created["id"], "Animals/Pet/Good Dog") in [(item["id"], item["tag"]) for item in rules]

        target = next(entry for entry in renamed if entry["path"] == "Animals/Pet/Good Dog")
        assert app.delete(f"/api/tags/{target['id']}").status_code == 200

        assert created["id"] not in [item["id"] for item in app.get("/api/rules").json()]

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


class TestDefaultRules:
    @allure.title("Installs the bundled rules on the default tags")
    def test_installed(self, app):
        paths = {entry["path"] for entry in _flatten(app.get("/api/tags").json())}
        assert {"Processing/Tilt", "Processing/Crop", "Animals/Wildlife/Horse"} <= paths

        rules = {item["id"]: item for item in app.get("/api/rules").json()}

        for tag, expression in RuleService.DEFAULT_RULES.items():
            rule = rules[RuleService._default_rule_id(tag)]
            assert rule["tag"] == tag
            assert rule["expression"] == expression
            assert rule["enabled"] is True

    @allure.title("Tags photos from the bundled object and processing rules")
    def test_apply(self, app):
        ids = _add_photos(
            app,
            [
                Photo(path="cat.jpg", filename="cat.jpg", objects=_detections("cat")),
                Photo(path="horse.jpg", filename="horse.jpg", objects=_detections("horse")),
                Photo(
                    path="tilt.jpg",
                    filename="tilt.jpg",
                    processing=[{"step": "tilt", "summary": "1.2°", "meta": {"applied": True, "crop_mode": "none"}}],
                ),
                Photo(
                    path="crop.jpg",
                    filename="crop.jpg",
                    processing=[
                        {"step": "tilt", "summary": "1.2°", "meta": {"applied": True, "crop_mode": "none"}},
                        {"step": "crop", "summary": "Trimmed"},
                    ],
                ),
                Photo(path="tiny.jpg", filename="tiny.jpg", objects=_detections("cat", surface=0.07)),
                Photo(path="unsure.jpg", filename="unsure.jpg", objects=_detections("horse", confidence=0.85)),
            ],
        )

        applied = app.post("/api/rules/apply")
        assert applied.status_code == 200, applied.text
        assert applied.json()["changed"] == 4

        tags = [app.get(f"/api/photos/{photo_id}/data").json()["tags"] for photo_id in ids]
        assert "Animals/Pet/Cat" in tags[0]
        assert "Animals/Wildlife/Horse" in tags[1]
        assert "Processing/Tilt" in tags[2]
        assert "Processing/Crop" in tags[3]
        assert not any(tag.startswith("Animals/") for tag in tags[4])  # too small
        assert not any(tag.startswith("Animals/") for tag in tags[5])  # too uncertain

    @allure.title("Does not restore a default rule the user deleted")
    def test_deleted_is_not_restored(self, app):
        rule_id = RuleService._default_rule_id("Animals/Pet/Dog")
        assert app.delete(f"/api/rules/{rule_id}").status_code == 200

        assert app.db(RuleService.install_default_rules()) == 0
        assert rule_id not in [item["id"] for item in app.get("/api/rules").json()]
