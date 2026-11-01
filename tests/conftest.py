from __future__ import annotations

from pathlib import Path

import pytest

from billing_sentinel import orchestrator
from billing_sentinel.config import Config, load_config
from billing_sentinel.domain import RunResult
from billing_sentinel.sources import InMemoryCostSource
from fixtures import oct2026

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def cfg() -> Config:
    return load_config(REPO / "config" / "example.toml")


@pytest.fixture(scope="session")
def oct_result(cfg: Config) -> RunResult:
    source = InMemoryCostSource(oct2026.build_rows())
    return orchestrator.run("report", oct2026.AS_OF, source, cfg, periods=oct2026.PERIODS)
