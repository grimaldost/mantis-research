"""Config-corpus compatibility gate (spec 0001 §8, invariant I4).

Every committed batch config under ``config/*.json`` must keep loading under the
current schema. This is I4's real-data check: a schema change that would reject
an existing config fails here (the dominant risk once config-schema PRs land in
this series). Later config-schema PRs (§9 primary, §10 research_prompt) rely on
this gate existing first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mantis_research.core.config import load_batch_config
from mantis_research.core.paths import project_root

if TYPE_CHECKING:
    from pathlib import Path

_CONFIG_DIR = project_root() / 'config'
_CONFIGS = sorted(_CONFIG_DIR.glob('*.json'))


def test_config_dir_is_non_empty() -> None:
    # Guard against the glob silently matching nothing (which would make the
    # parametrized test vacuously pass). The public repo ships example configs;
    # author your own alongside them.
    assert len(_CONFIGS) >= 1


@pytest.mark.parametrize('config_path', _CONFIGS, ids=lambda p: p.name)
def test_every_committed_config_loads(config_path: Path) -> None:
    cfg = load_batch_config(config_path)
    assert cfg.schema_version == 2
    assert cfg.batch_name
    assert cfg.topics  # every batch has at least one topic
