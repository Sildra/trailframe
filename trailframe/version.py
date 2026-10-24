from __future__ import annotations

from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version


@lru_cache(maxsize=1)
def app_version() -> str:
    """Return the installed package version, falling back to the generated VCS file."""
    try:
        return version("trailframe")
    except PackageNotFoundError:
        pass

    try:
        from trailframe._version import __version__
    except ImportError:
        return "0.0.0"

    return __version__
