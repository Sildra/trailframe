from __future__ import annotations

import ast
import asyncio
from importlib.metadata import Distribution, distributions, packages_distributions
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from trailframe.services.core.thread_pool_service import ThreadPoolService
from trailframe.services.pipelines.executor import run_in_thread

router = APIRouter(prefix="/api/about", tags=["about"])

_APP_ROOT = Path(__file__).resolve().parents[1]

_cached_packages: list[PackageInfo] | None = None
_packages_lock = asyncio.Lock()


class PackageInfo(BaseModel):
    name: str
    version: str
    license: str


def _imported_module_names() -> set[str]:
    names: set[str] = set()

    for path in _APP_ROOT.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.name.split(".", 1)[0])
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".", 1)[0])

    return names


def _package_license(dist: Distribution) -> str:
    metadata = dist.metadata

    for classifier in metadata.get_all("Classifier") or []:
        if classifier.startswith("License :: OSI Approved ::"):
            return classifier.split("::")[-1].strip()

    for key in ("License-Expression", "License"):
        value = metadata.get(key)
        if value:
            value = value.strip()
            if len(value) <= 80:
                return value

    return ""


def _build_packages() -> list[PackageInfo]:
    """Collect the packages imported by the app (blocking: walks the source tree and
    enumerates installed distributions, so callers run it off the event loop)."""
    installed = {dist.metadata.get("Name", "").casefold(): dist for dist in distributions()}
    module_distributions = packages_distributions()

    distribution_names: set[str] = set()

    for module in _imported_module_names():
        distribution_names.update(
            dist_name for dist_name in module_distributions.get(module, ()) if dist_name.casefold() in installed
        )

    packages: list[PackageInfo] = []

    for key in sorted(distribution_names, key=str.casefold):
        dist = installed.get(key.casefold())
        if dist is None:
            continue

        packages.append(
            PackageInfo(name=dist.metadata.get("Name", ""), version=dist.version, license=_package_license(dist))
        )

    return packages


@router.get("/packages", response_model=list[PackageInfo])
async def list_packages() -> list[PackageInfo]:
    global _cached_packages

    if _cached_packages is None:
        async with _packages_lock:
            if _cached_packages is None:
                _cached_packages = await run_in_thread(ThreadPoolService.get_executor(), _build_packages)

    return _cached_packages
