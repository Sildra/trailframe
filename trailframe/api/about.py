from __future__ import annotations

import ast
from importlib.metadata import Distribution, distributions, packages_distributions
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/about", tags=["about"])

_APP_ROOT = Path(__file__).resolve().parents[1]


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


@router.get("/packages", response_model=list[PackageInfo])
async def list_packages() -> list[PackageInfo]:
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
            PackageInfo(
                name=dist.metadata.get("Name", ""),
                version=dist.version,
                license=_package_license(dist),
            )
        )

    return packages
