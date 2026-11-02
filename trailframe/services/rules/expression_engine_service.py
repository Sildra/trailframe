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

from trailframe.services.rules.schema import schema
from trailframe.services.service import Service

BUNDLE_NAME = "expression.js"
DEV_BUNDLE = Path("frontend/dist-expression") / BUNDLE_NAME


class ExpressionEngineError(RuntimeError):
    """Raised when the JavaScript expression bundle cannot be loaded."""


class ExpressionEngineService(Service):
    """Text ↔ rule-AST conversion backed by the frontend parser bundle."""

    _name = "ExpressionEngine"

    _engine: ClassVar[MiniRacer | None] = None
    _lock: ClassVar[threading.RLock] = threading.RLock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    async def _start(cls) -> None:
        cls._ensure_engine()

    @classmethod
    async def _stop(cls) -> None:
        with cls._lock:
            if cls._engine is not None:
                cls._engine.close()
                cls._engine = None

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
    def _bundle_path(cls) -> Path:
        """Prefer the source-tree build, then the bundle shipped in the wheel."""
        dev = DEV_BUNDLE

        if dev.is_file():
            return dev

        return Path(str(resources.files("trailframe") / "frontend" / "dist-expression" / BUNDLE_NAME))

    @classmethod
    def _ensure_engine(cls) -> MiniRacer:
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
