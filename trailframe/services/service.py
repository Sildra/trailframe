import logging
from abc import ABC
from enum import Enum
from typing import ClassVar

from trailframe.log import get_logger
from trailframe.services.core.configuration_service import Node

_logger = get_logger()


class ServiceState(Enum):
    NOT_STARTED = "not started"
    STARTED = "started"
    START_FAILED = "starting failure"


class Service(ABC):
    _name: str | None = None
    _state = ServiceState.NOT_STARTED
    _reconfig_safe: ClassVar[bool] = True
    _requires: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def configure(cls, config: Node) -> None:
        if cls._state is ServiceState.STARTED and not cls._reconfig_safe:
            cls._log("configuration changes will be applied on next start")
            return

        cls._configure(config)
        cls._log("configured")

    @classmethod
    async def start(cls) -> None:
        if cls._state is ServiceState.STARTED:
            return

        try:
            cls._require_started()
            await cls._start()
        except Exception as exception:
            cls._state = ServiceState.START_FAILED
            cls._log(f"start failed: {exception}")
            raise

        cls._state = ServiceState.STARTED
        cls._log("started")

    @classmethod
    def _require_started(cls) -> None:
        """Verify that every service in `_requires` has already been started.

        Only direct dependencies are declared — transitively started services
        are guaranteed through their own requirements. Services are referenced
        by name (resolved against the ServiceRegistry at start time) so that
        modules with circular import relationships can still declare them.
        """
        missing = [name for name in cls._requires if not cls._is_started(cls._resolve_required(name))]

        if missing:
            message = f"{cls.get_name()} requires started services: {', '.join(missing)}"
            cls._log(message, logging.ERROR)
            raise RuntimeError(message)

    @classmethod
    def _is_started(cls, service: "type[Service] | None") -> bool:
        return service is not None and service.get_state() is ServiceState.STARTED

    @classmethod
    def _resolve_required(cls, name: str) -> "type[Service] | None":
        from trailframe.services.service_registry import ServiceRegistry

        for service in ServiceRegistry.get_services():
            if service.get_name() == name:
                return service

        return None

    @classmethod
    async def stop(cls) -> None:
        if cls._state is ServiceState.NOT_STARTED:
            return

        await cls._stop()
        cls._state = ServiceState.NOT_STARTED
        cls._log("stopped")

    @classmethod
    def get_name(cls) -> str:
        return cls._name or cls.__name__

    @classmethod
    def get_state(cls) -> ServiceState:
        return cls._state

    @classmethod
    def _log(cls, message: str, level: int = logging.INFO) -> None:
        _logger.log(level, f"[{cls.get_name()}] {message}")

    @classmethod
    def _configure(cls, config: Node) -> None:
        """Read configuration from the root node.

        Services that rely on parameters under the `general` node start with
        `general_node = config.get_node("general", "General parameters")`.
        """

    @classmethod
    async def _start(cls) -> None:
        pass

    @classmethod
    async def _stop(cls) -> None:
        pass
