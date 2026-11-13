"""Run the editor's expression parser and printer inside the server process.

The expression language is implemented once, in TypeScript, and built into a
small standalone bundle (`frontend/dist-expression/expression.js`). Loading that
bundle in an embedded V8 (`mini-racer`) lets Python convert text to the rule AST
and back without maintaining a second parser.
"""

from __future__ import annotations

import json
import threading
from importlib import resources
from pathlib import Path
from typing import Any, ClassVar

from py_mini_racer import MiniRacer

from trailframe.services.core.configuration_service import Node
from trailframe.services.rules.schema import schema
from trailframe.services.service import Service, ServiceState

BUNDLE_NAME = "expression.js"
DEV_BUNDLE = Path("frontend/dist-expression") / BUNDLE_NAME
JAVASCRIPT_CONFIG = "javascript_modules"


class ExpressionEngineError(RuntimeError):
    """Raised when the JavaScript expression bundle cannot be loaded."""


class ExpressionEngineService(Service):
    """Text ↔ rule-AST conversion backed by the frontend parser bundle."""

    _name = "ExpressionEngine"

    _engine: ClassVar[MiniRacer | None] = None
    _lock: ClassVar[threading.RLock] = threading.RLock()
    _general: ClassVar[Node | None] = None
    _enabled: ClassVar[bool] = True

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def _configure(cls, config: Node) -> None:
        cls._general = config.get_node("general", "General parameters")

        # The initial pass runs before HardwareService decides the low-memory
        # default, so `_start` applies the flag once every service is configured.
        if cls._state is ServiceState.STARTED:
            cls._apply()

    @classmethod
    async def _start(cls) -> None:
        cls._apply()

    @classmethod
    async def _stop(cls) -> None:
        cls._release()
        cls._general = None

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------

    @classmethod
    def parse(cls, expression: str) -> dict[str, Any]:
        """Parse an expression with the editor's parser.

        Returns `{definition, issues}` exactly as the browser sees it; an invalid
        expression yields `definition: null` rather than an exception.
        """
        engine = cls._ensure_engine()

        with cls._lock:
            raw = engine.eval(
                "JSON.stringify(TrailframeExpression.parseExpression("
                f"{json.dumps(expression)}, globalThis.__trailframe_schema))"
            )

        return json.loads(raw)

    @classmethod
    def print(cls, definition: dict[str, Any]) -> str:
        """Render a rule AST back to canonical expression text."""
        engine = cls._ensure_engine()

        with cls._lock:
            return str(
                engine.eval(
                    f"TrailframeExpression.printDefinition({json.dumps(definition)}, globalThis.__trailframe_schema)"
                )
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @classmethod
    def _apply(cls) -> None:
        """Read the flag and load or release the engine to match it."""
        if cls._general is None:
            return

        cls._enabled = bool(
            cls._general.get_path_value(JAVASCRIPT_CONFIG, "Load JavaScript modules (the rule expression engine)", True)
        )

        if cls._enabled:
            cls._ensure_engine()
        else:
            cls._release()
            cls._log("JavaScript modules are disabled; expression parse/print is unavailable")

    @classmethod
    def _release(cls) -> None:
        with cls._lock:
            if cls._engine is not None:
                cls._engine.close()
                cls._engine = None

    @classmethod
    def _bundle_path(cls) -> Path:
        """Prefer the source-tree build, then the bundle shipped in the wheel."""
        dev = DEV_BUNDLE

        if dev.is_file():
            return dev

        return Path(str(resources.files("trailframe") / "frontend" / "dist-expression" / BUNDLE_NAME))

    @classmethod
    def _ensure_engine(cls) -> MiniRacer:
        if not cls._enabled:
            raise ExpressionEngineError("JavaScript modules are disabled; enable them under Configuration > General")

        if cls._engine is not None:
            return cls._engine

        with cls._lock:
            if cls._engine is not None:
                return cls._engine

            path = cls._bundle_path()

            if not path.is_file():
                raise ExpressionEngineError(
                    f"Expression bundle not found at {path}. Run `npm run build:expression` in frontend/."
                )

            engine = MiniRacer()
            engine.eval(path.read_text(encoding="utf-8"))
            engine.eval(f"globalThis.__trailframe_schema = {json.dumps(schema())};")
            cls._engine = engine

        return cls._engine
