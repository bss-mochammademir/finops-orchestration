import inspect
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from billing_sentinel import dispatch, render, scoring
from billing_sentinel.config import ConfigError, config_from_dict, default_config
from billing_sentinel.sources import BigQueryCostSource, CostSource, InMemoryCostSource

SRC = Path(__file__).resolve().parents[1] / "src" / "billing_sentinel"


def test_example_config_loads(cfg):
    assert cfg.thresholds.large_spike_pct == Decimal(100)
    assert cfg.thresholds.large_spike_delta_idr == Decimal(1_000_000)
    assert cfg.thresholds.anomaly_min_findings == 3
    assert cfg.lower_confidence_border == "#9aa5b1"
    assert cfg.review_space_key == "finops-review"
    assert cfg.config_version.startswith("2026.11-wp1+")


def test_defaults_match_example(cfg):
    d = default_config()
    assert d.thresholds == cfg.thresholds
    assert d.status_colors == cfg.status_colors


@pytest.mark.parametrize(
    "data",
    [
        {"routing": {"chat_webhook_url": "x"}},
        {"routing": {"api_key": "x"}},
        {"dispatch": {"bot_token": "x"}},
        {"routing": {"team_space_keys": {"t": "https://chat.example.invalid/x"}}},
    ],
)
def test_config_rejects_credentials_and_endpoints(data):
    with pytest.raises(ConfigError):
        config_from_dict(data)


def test_sources_protocol():
    assert isinstance(InMemoryCostSource([]), CostSource)
    assert isinstance(BigQueryCostSource("project.dataset.fact_daily_cost"), CostSource)
    with pytest.raises(NotImplementedError, match="WP2"):
        BigQueryCostSource("t").fetch(date(2026, 11, 1), date(2026, 11, 15))


@pytest.mark.parametrize(
    "fn, args, wp",
    [
        (render.render_technical_view, (None, None), "WP3"),
        (render.render_executive_email, (None, None), "WP3"),
        (render.render_pdf, (None, None), "WP4"),
        (dispatch.dispatch, (None, None), "WP2"),
        (dispatch.heartbeat, (None,), "WP2"),
        (scoring.score_v0, (None,), "WP4"),
    ],
)
def test_stubs_raise_not_implemented_with_wp_reference(fn, args, wp):
    with pytest.raises(NotImplementedError, match=wp):
        fn(*args)
    assert "TODO(WP" in inspect.getsource(inspect.getmodule(fn))


def test_no_source_file_emits_approval_wording():
    for path in SRC.glob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert "siap disetujui" not in text and "siap di-approve" not in text, path
