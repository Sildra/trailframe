from __future__ import annotations

import allure
import pytest

from trailframe.services.core.configuration_service import ConfigurationService, Node
from trailframe.services.pipelines.pipeline_service import PipelineService


class TestNode:
    @allure.title("Returns the default value and records the description")
    def test_get_path_value_creates_and_defaults(self):
        node = Node("root")
        assert node.get_path_value("a.b.c", "desc", 42) == 42
        # Defaults are persisted on the node and returned on later access
        assert node.get_path_value("a.b.c") == 42
        assert node.get_node("a.b.c").description == "desc"

    @allure.title("An explicit value overrides the default")
    def test_set_value_overrides_default(self):
        node = Node("root")
        node.get_path_value("x", default_value=1)
        node.get_node("x").set_value(2)
        assert node.get_path_value("x") == 2

    @allure.title("Tracks whether a value or default is present")
    def test_has_value_and_default(self):
        node = Node("root")
        assert not node.has_value
        node.get_node("v").set_value(1)
        assert node.get_node("v").has_value

    @allure.title("Serializes the node tree to a plain dict")
    def test_to_dict(self):
        node = Node("root")
        node.get_node("general.photos_folder").set_value("photos")
        node.get_node("general.port").set_value(8000)
        assert node.to_dict() == {"general": {"photos_folder": "photos", "port": 8000}}

    @allure.title("Serializes an empty node to None")
    def test_to_dict_empty_node_is_none(self):
        node = Node("root")
        assert node.to_dict() is None

    @allure.title("Round-trips a node tree through from_dict/to_dict")
    def test_roundtrip_from_dict_to_dict(self):
        data = {"general": {"port": 8000, "nested": {"flag": True}}}
        node = Node.from_dict("root", data)
        assert node.to_dict() == data

    @allure.title("Round-trips a node tree through JSON, keeping values and descriptions")
    def test_roundtrip_json(self):
        node = Node("root")
        node.get_node("general.port").set_value(8000)
        node.get_node("general.port").description = "Port"
        json_data = node.to_json()
        restored = Node.from_json("root", json_data)
        assert restored.get_path_value("general.port") == 8000
        assert restored.get_node("general.port").description == "Port"

    @allure.title("Round-trips an empty root through JSON")
    def test_empty_root_json(self):
        node = Node("root")
        assert Node.from_json("root", node.to_json()).to_dict() is None

    @allure.title("Describes scalar lists with an item descriptor")
    def test_json_describes_scalar_list(self):
        node = Node("general")
        node.get_node("thumbnail_sizes").set_value([160, 400])

        descriptor = node.to_json()["children"]["thumbnail_sizes"]["item"]
        assert descriptor["kind"] == "scalar"
        assert descriptor["scalar_type"] == "number"
        assert descriptor["template"] == 0

    @allure.title("Describes named-map lists with keys and a template")
    def test_json_describes_named_map_list(self):
        node = Node("root")
        node.get_node("pipelines").set_value([{"Basic": {"remote": "", "scanners": ["Object"]}}])

        descriptor = node.to_json()["children"]["pipelines"]["item"]
        assert descriptor["kind"] == "named-map"
        assert descriptor["keys"] == {"remote": "string", "scanners": "list-str"}
        assert descriptor["template"] == {"": {"remote": "", "scanners": []}}

    @allure.title("Omits untouched leaves from JSON output")
    def test_json_omits_untouched(self):
        node = Node("root")
        node.children["stale"] = Node("stale", value=1)
        node.get_node("kept").set_value(2)

        result = node.to_json(filter_touched=True)["children"]
        assert set(result) == {"kept"}

    @allure.title("Keeps structural parents of touched nodes in JSON output")
    def test_json_keeps_touched_descendants(self):
        node = Node("root")
        node.get_node("parent.child").set_value(1)

        result = node.to_json(filter_touched=True)["children"]
        assert set(result) == {"parent"}

    @allure.title("Includes all nodes without the touched filter")
    def test_json_includes_stale_without_filter(self):
        node = Node("root")
        node.children["stale"] = Node("stale", value=1)

        result = node.to_json()["children"]
        assert set(result) == {"stale"}


class TestConfigurationService:
    @allure.title("Loads YAML config and persists a changed value back to disk")
    def test_load_and_save(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("general:\n  port: 1234\n", encoding="utf-8")

        ConfigurationService.configure(config_file)
        ConfigurationService.load()
        assert ConfigurationService.root().get_path_value("general.port") == 1234

        ConfigurationService.root().get_node("general.port").set_value(5656)
        ConfigurationService.save()
        result = tmp_path / "config.yaml"
        assert "5656" in result.read_text(encoding="utf-8")

    @allure.title("Does not send stale nodes to the frontend")
    def test_to_json_filters_stale(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("general:\n  port: 1234\nlegacy:\n  old_key: true\nstray: 5\n", encoding="utf-8")

        ConfigurationService.configure(config_file)
        ConfigurationService.load()
        assert ConfigurationService.root().get_path_value("general.port") == 1234

        children = ConfigurationService.to_json()["children"]
        assert "general" in children
        assert "legacy" not in children
        assert "stray" not in children

        assert "stray: 5" in config_file.read_text(encoding="utf-8")

    @allure.title("Stale nodes leave the file when the frontend saves the filtered tree")
    def test_ui_save_drops_stale_nodes(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("general:\n  port: 1234\nstray: 5\n", encoding="utf-8")

        ConfigurationService.configure(config_file)
        ConfigurationService.load()
        assert ConfigurationService.root().get_path_value("general.port") == 1234

        ConfigurationService.from_json(ConfigurationService.to_json())
        ConfigurationService.save()

        text = config_file.read_text(encoding="utf-8")
        assert "port: 1234" in text
        assert "stray" not in text

    @allure.title("Yields an empty root when the config file is missing")
    def test_load_missing_file_yields_empty_root(self, tmp_path):
        config_file = tmp_path / "missing.yaml"
        ConfigurationService.configure(config_file)
        ConfigurationService.load()
        assert ConfigurationService.root().to_dict() is None

    @allure.title("Rejects a config file whose root is not a mapping")
    def test_load_rejects_non_mapping_root(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("- a\n- b\n", encoding="utf-8")
        ConfigurationService.configure(config_file)
        with pytest.raises(TypeError):
            ConfigurationService.load()

    @allure.title("Reconfiguring resets the configuration root")
    def test_configure_resets_root(self, tmp_path):
        ConfigurationService.configure(tmp_path / "a.yaml")
        ConfigurationService.root().get_node("x").set_value(1)
        ConfigurationService.configure(tmp_path / "b.yaml")
        assert ConfigurationService.root().to_dict() is None

    @allure.title("Exposes a pipelines section even when not configured")
    def test_to_json_injects_pipelines(self, tmp_path):
        ConfigurationService.configure(tmp_path / "c.yaml")
        ConfigurationService.load()

        assert "pipelines" not in ConfigurationService.to_json().get("children", {})

        payload = ConfigurationService.to_json()
        PipelineService.add_pipelines_payload(payload)
        children = payload["children"]

        value = children["pipelines"]["value"]

        assert {next(iter(entry)) for entry in value} == {"CreationPipeline", "BasicPipeline"}
        assert all(
            "File" not in next(iter(entry.values()))["scanners"]
            and "Database" not in next(iter(entry.values()))["scanners"]
            for entry in value
        )
        assert all(next(iter(entry.values()))["remote"] == "" for entry in value)

        scanners = children["pipelines"]["item"]["fields"]["scanners"]
        assert scanners["editor"] == "scanner"
        assert {option["name"] for option in scanners["options"]} == {
            "Activity",
            "EXIF",
            "Location",
            "Object",
            "PerceptualHash",
            "Thumbnail",
        }

    @allure.title("Exposes the configured pipelines instead of the defaults")
    def test_to_json_roundtrips_custom_pipelines(self):
        ConfigurationService._root = Node.from_dict(
            "root", {"pipelines": [{"Basic": {"remote": "", "scanners": ["Object"]}}]}
        )
        ConfigurationService._file = None

        PipelineService._parse_pipelines_config(ConfigurationService.root())

        payload = ConfigurationService.to_json()
        PipelineService.add_pipelines_payload(payload)
        children = payload["children"]

        assert children["pipelines"]["value"] == [{"Basic": {"remote": "", "scanners": ["Object"]}}]

        item = children["pipelines"]["item"]
        assert item["kind"] == "named-map"
        assert item["fields"]["scanners"]["editor"] == "scanner"

    @allure.title("Persists the pipelines section when the configuration is saved")
    def test_save_persists_pipelines(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        ConfigurationService.configure(config_file)

        payload = ConfigurationService.to_json()
        PipelineService.add_pipelines_payload(payload)
        ConfigurationService.from_json(payload)
        ConfigurationService.save()

        assert "pipelines" in config_file.read_text(encoding="utf-8")

    @allure.title("Raises when saving before configuring")
    def test_save_without_configure_raises(self):
        ConfigurationService._file = None
        with pytest.raises(RuntimeError):
            ConfigurationService.save()
