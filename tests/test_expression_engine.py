from __future__ import annotations

import allure

from trailframe.services.core.configuration_service import Node
from trailframe.services.rules.expression_engine_service import ExpressionEngineService
from trailframe.services.service import ServiceState


class TestExpressionEngine:
    @allure.title("Converts expression text into the same definition the editor builds")
    def test_parse(self, app):
        response = app.post(
            "/api/rules/expression/parse",
            json={"expression": 'objects [label = "dog" and confidence >= 80%] has any and exif.FNumber >= f/2.8'},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["issues"] == []
        assert body["definition"]["conditions"][0] == {
            "type": "collection",
            "path": "objects",
            "quantifier": "any",
            "condition": {
                "type": "group",
                "match": "all",
                "conditions": [
                    {"type": "element", "key": "label", "op": "eq", "value": "dog"},
                    {"type": "element", "key": "confidence", "op": "gte", "value": 0.8},
                ],
            },
        }
        assert body["definition"]["conditions"][1] == {
            "type": "scalar",
            "path": "exif.FNumber",
            "op": "gte",
            "value": 2.8,
        }

        invalid = app.post("/api/rules/expression/parse", json={"expression": "objects [meta.applied] has any"})

        assert invalid.status_code == 200
        assert invalid.json()["definition"] is None
        assert "comparison operator" in invalid.json()["issues"][0]["message"]

    @allure.title("Renders a definition back to canonical expression text")
    def test_print(self, app):
        parsed = app.post(
            "/api/rules/expression/parse",
            json={"expression": 'objects [label = "dog" and confidence >= 80%] has any and width >= 1200px'},
        ).json()

        response = app.post("/api/rules/expression/print", json={"definition": parsed["definition"]})

        assert response.status_code == 200
        assert (
            response.json()["expression"] == 'objects [label = "dog" and confidence >= 80%] has any and width >= 1200px'
        )

    @allure.title("Rejects expression conversion when JavaScript modules are disabled")
    def test_disabled_returns_service_unavailable(self, app, monkeypatch):
        from trailframe.services.rules.expression_engine_service import ExpressionEngineService

        monkeypatch.setattr(ExpressionEngineService, "_enabled", False)

        response = app.post("/api/rules/expression/parse", json={"expression": "width >= 1200px"})

        assert response.status_code == 503
        assert "JavaScript modules are disabled" in response.json()["detail"]


class TestJavascriptModulesConfig:
    @allure.title("Loads and releases the engine as the configuration flag changes")
    def test_toggles_engine_live(self, monkeypatch):
        config = Node("root")
        flag = config.get_node("general.javascript_modules")
        flag.set_value(True)
        monkeypatch.setattr(ExpressionEngineService, "_state", ServiceState.STARTED)

        try:
            ExpressionEngineService.configure(config)
            assert ExpressionEngineService._enabled is True
            assert ExpressionEngineService._engine is not None

            flag.set_value(False)
            ExpressionEngineService.configure(config)
            assert ExpressionEngineService._enabled is False
            assert ExpressionEngineService._engine is None
        finally:
            ExpressionEngineService._release()

    @allure.title("Does not load the engine on the initial configure pass")
    def test_initial_configure_defers_to_start(self, monkeypatch):
        config = Node("root")
        config.get_node("general.javascript_modules").set_value(False)

        monkeypatch.setattr(ExpressionEngineService, "_state", ServiceState.NOT_STARTED)
        ExpressionEngineService._release()
        ExpressionEngineService._configure(config)

        assert ExpressionEngineService._engine is None
