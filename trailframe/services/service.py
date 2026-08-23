from abc import ABC, abstractmethod
from enum import Enum

from trailframe.services.configuration_service import Node


class ServiceState(Enum):
    NOT_STARTED = "not started"
    STARTED = "started"
    START_FAILED = "starting failure"


class Service(ABC):
    _name: str | None = None
    _state = ServiceState.NOT_STARTED

    @classmethod
    def configure(cls, config: Node) -> None:
        cls._configure(config)
        cls._log("configured")

    @classmethod
    async def start(cls) -> None:
        if cls._state is ServiceState.STARTED:
            return

        try:
            await cls._start()
        except Exception as exception:
            cls._state = ServiceState.START_FAILED
            cls._log(f"start failed: {exception}")
            raise

        cls._state = ServiceState.STARTED
        cls._log("started")

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
    def _log(cls, message: str) -> None:
        print(f"[{cls.get_name()}] {message}", flush=True)

    @classmethod
    def _configure(cls, config: Node) -> None:
        pass

    @classmethod
    async def _start(cls) -> None:
        pass

    @classmethod
    async def _stop(cls) -> None:
        pass
