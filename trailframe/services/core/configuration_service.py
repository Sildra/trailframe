from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_UNDEFINED = object()


class Node:
    def __init__(
        self, name: str, description: str | None = None, value: Any = _UNDEFINED, default_value: Any = _UNDEFINED
    ):
        self.name = name
        self.description = description
        self.value = value
        self.default_value = default_value
        self.children: dict[str, Node] = {}
        self._touched = False

    @property
    def has_value(self) -> bool:
        return self.value is not _UNDEFINED

    @property
    def has_default_value(self) -> bool:
        return self.default_value is not _UNDEFINED

    def get_node(self, path: str, description: str | None = None) -> Node:
        current = self

        for part in path.split("."):
            if not part:
                continue

            child = current.children.get(part)

            if child is None:
                child = Node(part)
                current.children[part] = child

            current = child

        if description is not None:
            current.description = description

        return current

    def set_default_value(self, default_value: Any):
        if not self.has_value:
            self.value = default_value
        if not self.has_default_value:
            self.default_value = default_value

    def get_value(self, default_value: Any = _UNDEFINED) -> Any:
        self.set_default_value(default_value)
        self._touched = True

        return self.value

    def get_path_value(self, path: str, description: str | None = None, default_value: Any = _UNDEFINED) -> Any:
        return self.get_node(path, description).get_value(default_value)

    def set_value(self, value: Any) -> None:
        self.value = value
        self._touched = True

    def _is_kept(self) -> bool:
        if self._touched:
            return True

        return any(child._is_kept() for child in self.children.values())

    def to_dict(self) -> Any:
        if not self.children:
            return None if not self.has_value else self.value

        return {name: child.to_dict() for name, child in self.children.items()}

    @staticmethod
    def _value_type(value: Any) -> str:
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, (int, float)):
            return "number"
        if isinstance(value, list):
            return "list-str" if all(isinstance(item, str) for item in value) else "list"
        return "string"

    @staticmethod
    def _default_value(value_type: str) -> Any:
        return {"bool": False, "number": 0, "list": [], "list-str": [], "string": ""}.get(value_type, "")

    def _item_descriptor(self) -> dict[str, Any] | None:
        value = self.value

        if not isinstance(value, list) or not value:
            return None

        kind = "scalar"
        scalar_type = self._value_type(value[0])
        keys: dict[str, str] = {}
        named_key: str | None = None

        for item in value:
            if isinstance(item, dict):
                if len(item) == 1 and isinstance(next(iter(item.values())), dict):
                    name, settings = next(iter(item.items()))

                    if named_key is None:
                        named_key = name
                    elif named_key != name:
                        named_key = ""
                    kind = "named-map"

                    for key, field in settings.items():
                        keys[key] = self._value_type(field)
                else:
                    kind = "map"

                    for key, field in item.items():
                        keys[key] = self._value_type(field)
            elif isinstance(item, list):
                kind = "array"
            elif kind == "scalar":
                scalar_type = self._value_type(item)

        descriptor: dict[str, Any] = {"kind": kind}

        if kind == "scalar":
            descriptor["scalar_type"] = scalar_type
            descriptor["template"] = self._default_value(scalar_type)
        elif kind == "named-map":
            descriptor["keys"] = keys
            descriptor["template"] = {"": {key: self._default_value(item_type) for key, item_type in keys.items()}}
        else:
            descriptor["keys"] = keys
            descriptor["template"] = {key: self._default_value(item_type) for key, item_type in keys.items()}

        return descriptor

    def to_json(self, filter_touched: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {}

        if self.has_value:
            result["value"] = self.value

        if self.description is not None:
            result["description"] = self.description

        if isinstance(self.value, list):
            descriptor = self._item_descriptor()

            if descriptor is not None:
                result["item"] = descriptor

        if self.children:
            children = {}

            for name, child in self.children.items():
                if filter_touched and not child._is_kept():
                    continue

                children[name] = child.to_json(filter_touched)

            if filter_touched or children:
                result["children"] = children

        return result

    @classmethod
    def from_dict(cls, name: str, data: Any) -> Node:
        node = cls(name)

        if not isinstance(data, dict):
            node.value = data
            return node

        for child_name, child_data in data.items():
            node.children[child_name] = cls.from_dict(child_name, child_data)

        return node

    @classmethod
    def from_json(cls, name: str, data: Any) -> Node:
        node = cls(name)

        if not isinstance(data, dict):
            node.value = data
            return node

        if "value" in data:
            node.value = data["value"]

        if "description" in data:
            node.description = data["description"]

        for child_name, child_data in data.get("children", {}).items():
            node.children[child_name] = cls.from_json(child_name, child_data)

        return node


class ConfigurationService:
    _file: Path | None = None
    _root = Node("root")

    @classmethod
    def configure(cls, file: Path) -> None:
        cls._file = file
        cls._root = Node("root")

    @classmethod
    def load(cls) -> None:
        if cls._file is None:
            raise RuntimeError("ConfigurationService has not been configured")

        cls._root = Node("root")

        if not cls._file.exists():
            return

        with cls._file.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}

        if not isinstance(data, dict):
            raise TypeError("Configuration root must be a mapping")

        for name, value in data.items():
            cls._root.children[name] = Node.from_dict(name, value)

    @classmethod
    def save(cls) -> None:
        if cls._file is None:
            raise RuntimeError("ConfigurationService has not been configured")

        cls._file.parent.mkdir(parents=True, exist_ok=True)

        with cls._file.open("w", encoding="utf-8") as file:
            yaml.safe_dump(cls._root.to_dict(), file, sort_keys=False, allow_unicode=True)

    @classmethod
    def root(cls) -> Node:
        return cls._root

    @classmethod
    def to_json(cls) -> dict[str, Any]:
        return cls._root.to_json(filter_touched=True)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> None:
        cls._root = Node.from_json("root", data)
