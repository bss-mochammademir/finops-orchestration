"""Orchestration, idempotency (spec §2 IN.6) and report-mode periods (IN.5)."""

from datetime import date
from decimal import Decimal

import pytest

from billing_sentinel import orchestrator
from billing_sentinel.config import config_from_dict
from billing_sentinel.domain import CostRow, Period
from billing_sentinel.money import format_idr
from billing_sentinel.periods import resolve_periods
from billing_sentinel.sources import InMemoryCostSource


def _series(period: Period, per_day: int, project="bss-prod-x-1", last=None):
    rows = []
    for d in period.dates():
        amount = last if (last is not None and d == period.end) else per_day
        rows.append(CostRow(d, project, "Compute Engine", Decimal(amount), app_category_code="ac_050"))
    return rows


@pytest.fixture()
def nov_source():
    cur = Period(date(2026, 11, 16), date(2026, 11, 30))
    mom = Period(date(2026, 10, 16), date(2026, 10, 31))
    ph = Period(date(2026, 11, 1), date(2026, 11, 15))
    return InMemoryCostSource(_series(cur, 100_000) + _series(mom, 100_000) + _series(ph, 90_000))


# --- idempotency --------------------------------------------------------------
def test_run_id_same_for_same_mode_period_config(cfg, nov_source):
    a = orchestrator.run("report", date(2026, 12, 3), nov_source, cfg)
    b = orchestrator.run("report", date(2026, 12, 3), nov_source, cfg)
    c = orchestrator.run("report", date(2026, 12, 10), nov_source, cfg)  # same period
    assert a.run_id == b.run_id == c.run_id
    assert a == b


def test_run_id_changes_with_mode_period_or_config(cfg, nov_source):
    base = orchestrator.make_run_id("report", resolve_periods("report", date(2026, 12, 3)).current, cfg.config_version)
    other_period = orchestrator.make_run_id(
        "report", resolve_periods("report", date(2026, 12, 18)).current, cfg.config_version
    )
    other_mode = orchestrator.make_run_id("triage", resolve_periods("report", date(2026, 12, 3)).current, cfg.config_version)
    other_cfg = config_from_dict({"version": cfg.version, "thresholds": {"spike_pct_min": 30}})
    changed = orchestrator.make_run_id("report", resolve_periods("report", date(2026, 12, 3)).current, other_cfg.config_version)
    assert len({base, other_period, other_mode, changed}) == 4


# --- report periods + daily average ----------------------------------------
def test_report_run_2026_12_03_periods_and_daily_avg(cfg, nov_source):
    r = orchestrator.run("report", date(2026, 12, 3), nov_source, cfg)
    assert r.periods.current == Period(date(2026, 11, 16), date(2026, 11, 30))
    assert r.periods.mom == Period(date(2026, 10, 16), date(2026, 10, 31))
    assert r.total.cur == Decimal(1_500_000) and r.total.prior == Decimal(1_600_000)
    # Totals differ only because of period length; daily averages are equal.
    assert r.daily_avg_cur == r.daily_avg_prior == Decimal(100_000)
    assert "rata-rata harian" in r.narrative and format_idr(r.daily_avg_cur) in r.narrative
    assert r.secondary_total is not None and r.secondary_total.prior == Decimal(1_350_000)
    assert r.validation.ok, r.validation.violations


def test_lag_note_added_automatically(cfg):
    cur = Period(date(2026, 11, 16), date(2026, 11, 30))
    mom = Period(date(2026, 10, 16), date(2026, 10, 31))
    src = InMemoryCostSource(_series(cur, 100_000, last=50_000) + _series(mom, 100_000))
    r = orchestrator.run("report", date(2026, 12, 3), src, cfg)
    assert any("2026-11-30" in n and "belum lengkap" in n for n in r.notes)


def test_no_lag_note_on_complete_data(cfg, nov_source):
    r = orchestrator.run("report", date(2026, 12, 3), nov_source, cfg)
    assert not any("belum lengkap" in n for n in r.notes)


# --- quality gate routing / graceful degradation ---------------------------
class _BadProvider:
    def generate(self, result, cfg):
        return "Total biaya Rp1,5 miliar, invoice siap disetujui."


class _FailingProvider:
    def generate(self, result, cfg):
        raise TimeoutError("model timeout")


def test_invalid_narrative_routes_to_review(cfg, nov_source):
    r = orchestrator.run("report", date(2026, 12, 3), nov_source, cfg, narrative_provider=_BadProvider())
    assert r.route == "review"
    assert {"shorthand_mismatch", "approval_wording"} <= r.validation.codes()


def test_provider_failure_falls_back_to_template(cfg, nov_source):
    r = orchestrator.run("report", date(2026, 12, 3), nov_source, cfg, narrative_provider=_FailingProvider())
    assert r.route == "dispatch" and r.validation.ok
    assert r.narrative.startswith("Total net cost GCP periode")
    assert any("TimeoutError" in n for n in r.notes)


def test_unmapped_project_listed(cfg):
    cur = Period(date(2026, 11, 16), date(2026, 11, 30))
    rows = [CostRow(cur.start, "bss-prod-new-1", "Cloud Run", Decimal(10))]
    r = orchestrator.run("report", date(2026, 12, 3), InMemoryCostSource(rows), cfg)
    assert r.unmapped_projects == ("bss-prod-new-1",)
    assert r.coverage_adr003 == 0
    assert any("Belum Terpetakan" in n for n in r.notes)
