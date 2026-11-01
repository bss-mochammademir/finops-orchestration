"""Validator / quality gate (spec §2 IN.2, IN.4, IN.5; lessons §8.1, §8.3, §8.9)."""

import dataclasses
from datetime import date
from decimal import Decimal

from billing_sentinel.domain import (
    FindingEvent,
    FindingState,
    Line,
    Period,
    Status,
)
from billing_sentinel.validator import (
    check_finding_events,
    check_narrative_numbers,
    check_no_approval_wording,
    last_day_lag_note,
    validate_run,
)

COMPUTED = [Decimal(699561), Decimal(47587313)]


def codes(violations):
    return {v.code for v in violations}


# --- Rupiah shorthand bug (lessons §8.1) -----------------------------------
def test_shorthand_ribu_accepted():
    assert check_narrative_numbers("Places API sekitar Rp699 ribu.", COMPUTED) == []


def test_shorthand_juta_rejected():
    assert codes(check_narrative_numbers("Places API sekitar Rp699 juta.", COMPUTED)) == {"shorthand_mismatch"}


def test_shorthand_decimal_juta_rejected():
    assert codes(check_narrative_numbers("Places API sekitar Rp6,9 juta.", COMPUTED)) == {"shorthand_mismatch"}


def test_full_amount_must_be_computed():
    assert check_narrative_numbers("Total Rp47.587.313.", COMPUTED) == []
    assert codes(check_narrative_numbers("Total Rp47.587.314.", COMPUTED)) == {"unknown_amount"}
    assert codes(check_narrative_numbers("Ada biaya Rp1.000.000 baru.", COMPUTED)) == {"unknown_amount"}


def test_percentage_must_be_computed():
    pcts = [Decimal("7.1398984")]
    assert check_narrative_numbers("naik +7,14%", COMPUTED, pcts) == []
    assert check_narrative_numbers("naik +7,1%", COMPUTED, pcts) == []
    assert codes(check_narrative_numbers("naik +8,14%", COMPUTED, pcts)) == {"unknown_percentage"}
    assert codes(check_narrative_numbers("turun -7,14%", COMPUTED, pcts)) == {"unknown_percentage"}


def test_regression_narrative_with_invented_number_rejected(oct_result, cfg):
    bad = oct_result.narrative + " Potensi penghematan Rp3.000.000."
    report = validate_run(oct_result, cfg, narrative=bad)
    assert "unknown_amount" in report.codes()
    bad2 = oct_result.narrative.replace("Rp47.587.313", "Rp47,6 miliar")
    assert "shorthand_mismatch" in validate_run(oct_result, cfg, narrative=bad2).codes()
    ok = oct_result.narrative.replace("Rp47.587.313", "Rp47,6 juta")
    assert validate_run(oct_result, cfg, narrative=ok).ok


# --- approval wording (F-6) --------------------------------------------------
def test_approval_wording_rejected(oct_result, cfg):
    for phrase in ("Tagihan SIAP DISETUJUI.", "Invoice siap di-approve", "siap disetujui"):
        assert codes(check_no_approval_wording(phrase)) == {"approval_wording"}
    assert check_no_approval_wording("tidak ada temuan yang menghambat approval") == []
    assert "approval_wording" in validate_run(oct_result, cfg, narrative="Laporan siap disetujui.").codes()


# --- reconciliation of two views -------------------------------------------
def test_reconciliation_detects_mismatch(oct_result, cfg):
    cats = list(oct_result.views["category"])
    cats[0] = Line(cats[0].key, cats[0].cur + Decimal(100), cats[0].prior)
    broken = dataclasses.replace(oct_result, views={**oct_result.views, "category": tuple(cats)})
    report = validate_run(broken, cfg)
    assert "reconciliation" in report.codes()


def test_reconciliation_within_rounding_tolerance(oct_result, cfg):
    cats = list(oct_result.views["category"])
    cats[0] = Line(cats[0].key, cats[0].cur + Decimal(40), cats[0].prior)
    nudged = dataclasses.replace(oct_result, views={**oct_result.views, "category": tuple(cats)})
    assert "reconciliation" not in validate_run(nudged, cfg).codes()


# --- status consistency -------------------------------------------------------
def test_status_inconsistent_with_findings(oct_result, cfg):
    wrong = dataclasses.replace(oct_result, status=Status.NORMAL, status_color="#2e7d32")
    assert "status_inconsistent" in validate_run(wrong, cfg).codes()
    wrong_color = dataclasses.replace(oct_result, status_color="#2e7d32")
    assert "status_color" in validate_run(wrong_color, cfg).codes()


# --- finding_events -----------------------------------------------------------
def test_ack_normal_without_expiry_rejected():
    ev = FindingEvent("abc", FindingState.ACKNOWLEDGED_NORMAL, date(2026, 11, 2), reason="planned")
    assert codes(check_finding_events([ev])) == {"ack_without_expiry"}


def test_ack_normal_with_expiry_accepted(oct_result, cfg):
    ev = FindingEvent(
        "abc", FindingState.ACKNOWLEDGED_NORMAL, date(2026, 11, 2), reason="planned", expires_on=date(2026, 12, 31)
    )
    assert check_finding_events([ev]) == []
    other = FindingEvent("abc", FindingState.INVESTIGATING, date(2026, 11, 2))
    assert check_finding_events([other]) == []
    bad = FindingEvent("abc", FindingState.ACKNOWLEDGED_NORMAL, date(2026, 11, 2))
    assert "ack_without_expiry" in validate_run(oct_result, cfg, events=[bad]).codes()


# --- last-day lag (lessons §8.3) ---------------------------------------------
def _daily(period, normal, last):
    d = {day: Decimal(normal) for day in period.dates()}
    d[period.end] = Decimal(last)
    return d


def test_lag_note_when_last_day_below_70pct_median():
    p = Period(date(2026, 10, 18), date(2026, 10, 31))
    note = last_day_lag_note(_daily(p, 3_500_000, 2_000_000), p, Decimal("0.7"))
    assert note is not None and "2026-10-31" in note and "Rp2.000.000" in note


def test_legacy_31_oct_case_is_borderline_at_70pct():
    """Lessons §8.3: Rp2.463.398 vs ~Rp3.500.000 is 70,4% -> NOT flagged at ratio 0,7.

    Kept as an explicit test so that the threshold choice is reviewed by a human
    (a ratio of 0,75 would flag it).
    """
    p = Period(date(2026, 10, 18), date(2026, 10, 31))
    daily = _daily(p, 3_500_000, 2_463_398)
    assert last_day_lag_note(daily, p, Decimal("0.7")) is None
    assert last_day_lag_note(daily, p, Decimal("0.75")) is not None


def test_no_lag_note_at_or_above_threshold():
    p = Period(date(2026, 10, 18), date(2026, 10, 31))
    assert last_day_lag_note(_daily(p, 3_500_000, 2_450_000), p, Decimal("0.7")) is None  # exactly 70%
    assert last_day_lag_note(_daily(p, 3_500_000, 3_400_000), p, Decimal("0.7")) is None


def test_lag_ignores_degenerate_series():
    p = Period(date(2026, 10, 31), date(2026, 10, 31))
    assert last_day_lag_note({}, p, Decimal("0.7")) is None
    p2 = Period(date(2026, 10, 30), date(2026, 10, 31))
    assert last_day_lag_note({}, p2, Decimal("0.7")) is None
