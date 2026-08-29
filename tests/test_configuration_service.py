from __future__ import annotations

import allure
import pytest

from trailframe.services.core.configuration_service import ConfigurationService, Node


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

    @allure.title("Raises when saving before configuring")
    def test_save_without_configure_raises(self):
        ConfigurationService._file = None
        with pytest.raises(RuntimeError):
            ConfigurationService.save()
