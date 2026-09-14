import copy
from typing import Any, ClassVar

from sqlalchemy import select

from trailframe.models.photo import Photo
from trailframe.services.core.configuration_service import Node
from trailframe.services.core.database_service import DatabaseService
from trailframe.services.pipelines.item import Item
from trailframe.services.pipelines.pipeline import Pipeline
from trailframe.services.scanners import create_scanner
from trailframe.services.scanners.remote_scanner import RemoteScanner
from trailframe.services.scanners.scanner import ForceFlag, Scanner
from trailframe.services.service import Service, ServiceState


class PipelineService(Service):
    _requires = ("DatabaseService",)
    _pipelines: ClassVar[list[Pipeline]] = []
    _reconfigure_summary: ClassVar[dict[str, list[str]]] = {}

    DEFAULT_PIPELINES: ClassVar[list[dict[str, Any]]] = [
        {"CreationPipeline": {"remote": "", "scanners": ["EXIF", "Thumbnail"]}},
        {"BasicPipeline": {"remote": "", "scanners": ["Activity", "Location", "Object", "PerceptualHash"]}},
    ]

    PIPELINES_TEMPLATE: ClassVar[dict[str, Any]] = {
        "description": "Custom processing pipelines, in order. A local pipeline runs its scanners locally; a remote pipeline delegates the listed scanners to another Trailframe server.",
        "item": {
            "kind": "named-map",
            "keys": {"remote": "string", "scanners": "list-str"},
            "template": {"": {"remote": "", "scanners": []}},
        },
    }

    @classmethod
    def add_pipelines_payload(cls, payload: dict[str, Any]) -> None:
        """Assemble the editable pipelines section of a configuration payload for the frontend."""
        children = payload.setdefault("children", {})
        pipelines = children.get("pipelines")

        if not isinstance(pipelines, dict) or not isinstance(pipelines.get("value"), list) or pipelines["value"] == []:
            pipelines = children["pipelines"] = cls._default_pipelines_node()

        pipelines.setdefault("description", cls.PIPELINES_TEMPLATE["description"])
        cls._attach_scanner_chooser(pipelines)

    @classmethod
    def _default_pipelines_node(cls) -> dict[str, Any]:
        node = copy.deepcopy(cls.PIPELINES_TEMPLATE)
        node["value"] = copy.deepcopy(cls.DEFAULT_PIPELINES)

        return node

    @staticmethod
    def _attach_scanner_chooser(pipelines: Any) -> None:
        item = pipelines.get("item")

        if not isinstance(item, dict) or item.get("kind") != "named-map":
            return

        fields = item.get("fields")

        if not isinstance(fields, dict):
            fields = item["fields"] = {}

        if "scanners" in fields:
            return

        from trailframe.services.scanners import get_scanner_definitions

        fields["scanners"] = {
            "editor": "scanner",
            "options": [
                {
                    "name": definition["name"],
                    "can_be_disabled": definition["can_be_disabled"],
                    "can_be_remote": definition["can_be_remote"],
                }
                for definition in get_scanner_definitions()
                if definition["can_be_disabled"]
            ],
        }

    @staticmethod
    def _normalize_pipeline_entry(item: Any) -> dict | None:
        if not isinstance(item, dict) or len(item) != 1:
            return None

        name, settings = next(iter(item.items()))

        if not isinstance(settings, dict):
            return None

        scanners = settings.get("scanners", [])

        if not isinstance(scanners, list):
            scanners = []

        return {
            "name": str(name),
            "remote": settings.get("remote") or "",
            "scanners": [str(scanner) for scanner in scanners],
        }

    @staticmethod
    def _parse_pipelines_config(config: Node) -> list[dict] | None:
        node = config.get_node("pipelines")

        if not node.has_value or not isinstance(node.value, list):
            return None

        entries: list[dict] = []

        for item in node.get_value():
            if entry := PipelineService._normalize_pipeline_entry(item):
                entries.append(entry)

        return entries

    @classmethod
    def _build_pipeline(cls, entry: dict, index: int) -> Pipeline:
        scanners: list[Scanner] = []
        internal = {"File", "Database"}
        scanner_names = [name for name in entry["scanners"] if name not in internal]

        if index == 0 and not entry.get("remote") and (file_scanner := create_scanner("File")):
            scanners.append(file_scanner)

        if entry.get("remote"):
            scanners.append(RemoteScanner(str(entry["remote"]), scanner_names))
        else:
            for name in scanner_names:
                if scanner := create_scanner(name):
                    scanners.append(scanner)

        if database := create_scanner("Database"):
            scanners.append(database)

        return Pipeline(str(entry["name"]), scanners)

    @classmethod
    def _signature(cls, pipeline: Pipeline) -> tuple[str, str, tuple[str, ...]]:
        remote = ""
        scanners: list[str] = []

        for scanner in pipeline._scanners:
            if isinstance(scanner, RemoteScanner):
                remote = scanner._remote
                scanners.extend(scanner._scanner_names)
            else:
                scanners.append(scanner.name)

        return pipeline._name, remote, tuple(scanners)

    @classmethod
    def _configure(cls, config: Node) -> None:
        if cls.get_state() is ServiceState.STARTED:
            cls._reconfigure_live(config)
            return

        entries = cls._parse_pipelines_config(config)

        if not entries:
            config.get_node("pipelines").set_value(cls.DEFAULT_PIPELINES)
            entries = [
                entry for entry in (cls._normalize_pipeline_entry(item) for item in cls.DEFAULT_PIPELINES) if entry
            ]

        cls._pipelines = [cls._build_pipeline(entry, index) for index, entry in enumerate(entries)]
        cls._log(f"Loaded {len(cls._pipelines)} pipeline(s) from config")

        for pipeline in cls._pipelines:
            pipeline.configure(config)

    @classmethod
    def _reconfigure_live(cls, config: Node) -> None:
        entries = cls._parse_pipelines_config(config)

        if not entries:
            for pipeline in cls._pipelines:
                pipeline.configure(config)

            summary = {
                "kept": [pipeline._name for pipeline in cls._pipelines],
                "migrated": [],
                "added": [],
                "removed": [],
            }
            cls._reconfigure_summary = summary
            cls._log(f"reconfigured live pipelines {summary!r}")
            return

        current = {pipeline._name: pipeline for pipeline in cls._pipelines}
        replacement: list[Pipeline] = []
        applied: dict[str, list[str]] = {"kept": [], "migrated": [], "added": [], "removed": []}

        for index, entry in enumerate(entries):
            if entry is None:
                continue

            expected = cls._build_pipeline(entry, index)
            existing = current.pop(entry["name"], None)

            if existing is not None and cls._signature(existing) == cls._signature(expected):
                existing.configure(config)
                replacement.append(existing)
                applied["kept"].append(entry["name"])
                continue

            if existing is not None:
                existing.stop()
                pending = existing.take_pending()
                action = "migrated"
            else:
                pending = []
                action = "added"

            expected.configure(config)

            if pending:
                for item in pending:
                    expected.add(item)

            expected.start()
            replacement.append(expected)
            applied[action].append(entry["name"])

        for name, removed in current.items():
            removed.stop()
            applied["removed"].append(name)

        cls._pipelines = replacement
        cls._reconfigure_summary = applied
        cls._log(f"reconfigured live pipelines {applied!r}")

    @classmethod
    async def _start(cls) -> None:
        for pipeline in cls._pipelines:
            pipeline.start()

    @classmethod
    async def _stop(cls) -> None:
        for pipeline in reversed(cls._pipelines):
            pipeline.stop()

    @classmethod
    async def next(cls, item: Any, pipeline: Pipeline | None = None) -> None:
        if pipeline is None:
            candidates = cls._pipelines
        else:
            try:
                index = cls._pipelines.index(pipeline)
            except ValueError:
                candidates = []
            else:
                candidates = cls._pipelines[index + 1 :]

        for candidate in candidates:
            if candidate.accepts(item):
                candidate.add(item)
                return

    @classmethod
    async def forced_scan(cls, scanner_names: list[str]) -> None:
        await cls.next(ForceFlag(scanner_names))

        async def _load_photos(session) -> list[Photo]:
            result = await session.execute(select(Photo).order_by(Photo.id.asc()))
            photos = list(result.scalars().all())

            for photo in photos:
                session.expunge(photo)

            return photos

        for photo in await DatabaseService.execute(_load_photos):
            await cls.next(Item(photo))

        await cls.next(ForceFlag([]))

    @classmethod
    def get_queue_size(cls) -> int:
        return sum(pipeline.get_queue_size() for pipeline in cls._pipelines)

    @classmethod
    def get_last_reconfigure(cls) -> dict[str, list[str]]:
        return cls._reconfigure_summary

    @classmethod
    def get_snapshot(cls) -> dict[str, Any]:
        message: dict[str, Any] = {
            f"{pipeline._name.removesuffix('Pipeline')}": pipeline.get_status_message() for pipeline in cls._pipelines
        }

        return message

    @classmethod
    def get_pipeline(cls, name: str) -> Pipeline | None:
        for pipeline in cls._pipelines:
            if pipeline._name == name:
                return pipeline

        return None

    @classmethod
    def _remote_scanner_entries(cls) -> list[tuple[str, RemoteScanner]]:
        entries: list[tuple[str, RemoteScanner]] = []

        for pipeline in cls._pipelines:
            for scanner in pipeline._scanners:
                if isinstance(scanner, RemoteScanner):
                    entries.append((pipeline._name, scanner))

        return entries

    @classmethod
    def get_remote_pipelines(cls) -> list[dict]:
        return [
            {"name": name, "remote": scanner._remote, "scanners": scanner._scanner_names}
            for name, scanner in cls._remote_scanner_entries()
        ]

    @classmethod
    def get_remote_pipeline(cls, name: str) -> dict | None:
        for pipeline_name, scanner in cls._remote_scanner_entries():
            if pipeline_name == name:
                return {"name": name, "remote": scanner._remote, "scanners": scanner._scanner_names}

        return None
