from __future__ import annotations

import allure


class TestExpressionEngine:
    @allure.title("Converts expression text into the same definition the editor builds")
    def test_parse(self, app):
        response = app.post(
            "/api/rules/expression/parse",
            json={"expression": 'objects has "dog" with confidence >= 80% and exif.FNumber >= f/2.8'},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["issues"] == []
        assert body["definition"]["conditions"][0]["metrics"] == [{"name": "confidence", "op": "gte", "value": 80}]
        assert body["definition"]["conditions"][1] == {
            "type": "scalar",
            "path": "exif.FNumber",
            "op": "gte",
            "value": 2.8,
        }

        invalid = app.post("/api/rules/expression/parse", json={"expression": "width >= 1200"})

        assert invalid.status_code == 200
        assert invalid.json()["definition"] is None
        assert invalid.json()["issues"][0]["message"] == "Expected the unit 'px' after the number"

    @allure.title("Renders a definition back to canonical expression text")
    def test_print(self, app):
        parsed = app.post(
            "/api/rules/expression/parse",
            json={"expression": 'objects has "dog" with confidence >= 80% and width >= 1200px'},
        ).json()

        response = app.post("/api/rules/expression/print", json={"definition": parsed["definition"]})

        assert response.status_code == 200
        assert response.json()["expression"] == 'objects has "dog" with confidence >= 80% and width >= 1200px'
