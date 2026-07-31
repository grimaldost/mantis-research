"""mantis-research — multi-model research pipeline harness."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    # Single source of truth: the version declared in pyproject.toml, read
    # back off the installed distribution. Keeps `mantis version` from
    # drifting away from the package metadata.
    __version__ = version('mantis-research')
except PackageNotFoundError:  # pragma: no cover — running from an unbuilt tree
    __version__ = '0+unknown'
