from __future__ import annotations

import allure
import pytest

from trailframe.services.core.configuration_service import Node
from trailframe.services.service import Service, ServiceState
from trailframe.services.service_registry import ServiceRegistry

_EVENTS: list[str] = []


class _Probe(Service):
    _label = "probe"

    @classmethod
    def _configure(cls, config: Node) -> None:
        _EVENTS.append(f"configure:{cls._label}")

    @classmethod
    async def _start(cls) -> None:
        _EVENTS.append(f"start:{cls._label}")

    @classmethod
    async def _stop(cls) -> None:
        _EVENTS.append(f"stop:{cls._label}")


class _Alpha(_Probe):
    _label = "alpha"


class _Beta(_Probe):
    _label = "beta"


class _Gamma(_Probe):
    _label = "gamma"


class _StaticProbe(_Probe):
    _label = "static"
    _reconfig_safe = False


class _NeedsBeta(_Probe):
    _label = "needs-beta"
    _requires = ("_Beta",)


class TestServiceRegistry:
    @pytest.fixture(autouse=True)
    def _services(self):
        _EVENTS.clear()
        old = ServiceRegistry._services
        ServiceRegistry._services = [_Alpha, _Beta, _Gamma]
        yield
        ServiceRegistry._services = old

    @allure.title("Configures services in registration order")
    def test_configure_order(self):
        ServiceRegistry.configure(Node("root"))
        assert _EVENTS == ["configure:alpha", "configure:beta", "configure:gamma"]

    @allure.title("Starts services in registration order and stops them in reverse")
    async def test_start_and_stop_order(self):
        await ServiceRegistry.start()
        await ServiceRegistry.stop()
        assert _EVENTS == ["start:alpha", "start:beta", "start:gamma", "stop:gamma", "stop:beta", "stop:alpha"]

    @allure.title("Exposes the registered services in order")
    def test_get_services(self):
        assert ServiceRegistry.get_services() == [_Alpha, _Beta, _Gamma]

    @allure.title("Appends a service registered via register()")
    def test_register(self):
        ServiceRegistry.register(_Beta)
        assert ServiceRegistry.get_services() == [_Alpha, _Beta, _Gamma, _Beta]

    @allure.title("Skips configuration while started for services that cannot be re-configured at runtime")
    def test_guarded_configure_skipped_when_started(self):
        _StaticProbe._state = ServiceState.STARTED
        try:
            _StaticProbe.configure(Node("root"))
        finally:
            _StaticProbe._state = ServiceState.NOT_STARTED
        assert _EVENTS == []

    @allure.title("Re-configures services that are safe at runtime even while started")
    def test_unguarded_configure_applied_when_started(self):
        _Alpha._state = ServiceState.STARTED
        try:
            _Alpha.configure(Node("root"))
        finally:
            _Alpha._state = ServiceState.NOT_STARTED
        assert _EVENTS == ["configure:alpha"]

    @allure.title("Blocks start when a required service is not started yet")
    async def test_requires_service_started(self):
        with pytest.raises(RuntimeError):
            await _NeedsBeta.start()
        assert _NeedsBeta.get_state() is ServiceState.START_FAILED

        _NeedsBeta._state = ServiceState.NOT_STARTED
        await _Beta.start()
        try:
            await _NeedsBeta.start()
        finally:
            await _NeedsBeta.stop()
            await _Beta.stop()

        assert _EVENTS == ["start:beta", "start:needs-beta", "stop:needs-beta", "stop:beta"]
