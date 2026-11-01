"""Legacy routine parity rules L1-L13 (chip FINOPS-WP1b).

Fixtures: ``fixtures/oct2026.py`` (regression totals) and the SYNTHETIC
``fixtures/legacy_synthetic.py`` + ``fixtures/legacy_history_v1.json``.
"""

import dataclasses
import inspect
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from billing_sentinel import analytics, orchestrator
from billing_sentinel.classify import classify, derive_status
from billing_sentinel.domain import (
    Confidence,
    CostRow,
    Finding,
    FindingType,
    Line,
    Mode,
    Period,
    Status,
    make_finding_key,
)
from billing_sentinel.history import (
    HistoryEntry,
    HistoryError,
    apply_history,
    consecutive_runs,
    gap_note,
    load_legacy_history,
    parse_legacy_history,
    to_findings_rows,
)
from billing_sentinel.money import format_idr
from billing_sentinel.narrative import format_date_id
from billing_sentinel.periods import legacy14_periods, resolve_periods
from billing_sentinel.render import build_plain_text, build_subject
from billing_sentinel.sources import InMemoryCostSource
from billing_sentinel.validator import check_finding_labels, validate_run
from fixtures import legacy_synthetic as S
from fixtures import oct2026

HISTORY_JSON = Path(__file__).parent / "fixtures" / "legacy_history_v1.json"


@pytest.fixture(scope="module")
def history():
    return load_legacy_history(HISTORY_JSON)


@pytest.fixture(scope="module")
def syn(cfg, history):
    return orchestrator.run("legacy14", S.AS_OF, InMemoryCostSource(S.build_rows()), cfg, history=history)


@pytest.fixture(scope="module")
def syn_no_history(cfg):
    return orchestrator.run("legacy14", S.AS_OF, InMemoryCostSource(S.build_rows()), cfg)


@pytest.fixture(scope="module")
def legacy_oct(cfg):
    return orchestrator.run("legacy14", oct2026.AS_OF, InMemoryCostSource(oct2026.build_rows()), cfg)


def _by_label(result):
    return {f.label: f for f in result.findings}


def _agg(rows_cur, rows_prior):
    return analytics.aggregate(rows_cur), analytics.aggregate(rows_prior)


def _rows(spec, day):
    return [CostRow(day, p, s, Decimal(v), sku_name=sku) for (p, s, sku), v in spec.items() if v]


D_CUR, D_PRI = date(2026, 11, 1), date(2026, 10, 18)


# --- L1 legacy14 periods -----------------------------------------------------
def test_l1_legacy14_periods_as_of_2026_11_01():
    ps = resolve_periods("legacy14", date(2026, 11, 1))
    assert ps.current == Period(date(2026, 10, 18), date(2026, 10, 31))
    assert ps.mom == Period(date(2026, 10, 4), date(2026, 10, 17))
    assert ps.prior_half is None
    assert ps == legacy14_periods(date(2026, 11, 1)) == oct2026.PERIODS


def test_l1_legacy14_crosses_month_and_year():
    ps = legacy14_periods(date(2027, 1, 5))
    assert ps.current == Period(date(2026, 12, 22), date(2027, 1, 4))
    assert ps.mom == Period(date(2026, 12, 8), date(2026, 12, 21))


def test_l1_legacy14_regression_totals_unchanged(legacy_oct, cfg):
    assert legacy_oct.mode is Mode.LEGACY14
    assert format_idr(legacy_oct.total.cur) == "Rp47.587.313"
    assert format_idr(legacy_oct.total.prior) == "Rp44.416.052"
    assert legacy_oct.top_projects == oct2026.EXPECTED_TOP3
    assert legacy_oct.status is Status.ANOMALI
    assert legacy_oct.validation.ok, legacy_oct.validation.violations


def test_l1_legacy14_run_id_differs_from_report_mode(legacy_oct, oct_result):
    assert legacy_oct.run_id != oct_result.run_id
    assert legacy_oct.total == oct_result.total


# --- L2 flag rules -----------------------------------------------------------
def test_l2_new_cost_source_and_abs_rise_vs_project(syn):
    f = _by_label(syn)
    assert f["syn-prod-a-1 — BigQuery"].rule == "new_cost_source"
    assert f["syn-prod-a-1 — BigQuery"].type is FindingType.TEMUAN_NAIK
    cr = f["syn-prod-c-1 — Cloud Run"]
    assert cr.rule == "abs_rise_vs_project" and cr.pct_change < 25
    assert cr.confidence is Confidence.NORMAL


def test_l2_near_zero_prior_counts_as_new_cost_source(cfg):
    cur, pri = _agg(
        _rows({("p", "Compute Engine", "x"): 1_000_000, ("p", "Firestore", "r"): 200_000}, D_CUR),
        _rows({("p", "Compute Engine", "x"): 1_000_000, ("p", "Firestore", "r"): 500}, D_PRI),
    )
    (f,) = [f for f in classify(cur, pri, cfg) if f.service_name == "Firestore"]
    assert f.rule == "new_cost_source"


def test_l2_small_rise_not_flagged(cfg):
    cur, pri = _agg(
        _rows({("p", "Compute Engine", "x"): 10_000_000, ("p", "Cloud Run", "r"): 1_200_000}, D_CUR),
        _rows({("p", "Compute Engine", "x"): 10_000_000, ("p", "Cloud Run", "r"): 1_000_000}, D_PRI),
    )
    assert classify(cur, pri, cfg) == ()  # +20%, delta 200k < 10% of project


# --- L3 periodic / annual ----------------------------------------------------
def test_l3_periodic_service_is_lower_confidence(syn, cfg):
    f = _by_label(syn)["syn-prod-d-1 — Cloud Domains"]
    assert f.confidence is Confidence.LOWER and "periodik" in f.note
    assert "Cloud Domains" in cfg.periodic_services


def test_l3_drop_to_exact_half_is_lower_confidence(syn):
    f = _by_label(syn)["syn-prod-d-1 — Looker Studio Pro"]
    assert f.type is FindingType.PENURUNAN_BESAR and f.confidence is Confidence.LOWER
    assert "1/2" in f.note


def test_l3_periodic_alone_never_reaches_highest_status(cfg):
    cur, pri = _agg(
        _rows({("p", "Compute Engine", "x"): 1_000_000, ("p", "Cloud Domains", "d"): 9_000_000}, D_CUR),
        _rows({("p", "Compute Engine", "x"): 1_000_000, ("p", "Cloud Domains", "d"): 1_000_000}, D_PRI),
    )
    findings = classify(cur, pri, cfg)
    assert [f.confidence for f in findings] == [Confidence.LOWER]
    assert derive_status(findings, cfg) is Status.PERLU_PERHATIAN


def test_l3_non_exact_drop_stays_normal(cfg):
    cur, pri = _agg(
        _rows({("p", "Cloud SQL", "v"): 1_150_000}, D_CUR), _rows({("p", "Cloud SQL", "v"): 2_400_000}, D_PRI)
    )
    (f,) = classify(cur, pri, cfg)
    assert f.type is FindingType.PENURUNAN_BESAR and f.confidence is Confidence.NORMAL


# --- L4 recurring / improved / already known ---------------------------------
def test_l4_recurring_below_threshold_still_flagged(syn, syn_no_history):
    f = _by_label(syn)["syn-dev-h-1 — Cloud Run"]
    assert f.rule == "recurring" and f.recurring_count == 3 and f.pct_change < 25
    assert f.confidence is Confidence.LOWER
    assert "syn-dev-h-1 — Cloud Run" not in _by_label(syn_no_history)


def test_l4_existing_finding_gets_recurring_count(syn):
    assert _by_label(syn)["syn-prod-c-1 — Cloud Run"].recurring_count == 4


def test_l4_two_runs_is_not_recurring(cfg, history):
    short = history[-1:]  # only one earlier run -> 2 runs incl. current < 3
    line = Line(("syn-dev-h-1", "Cloud Run"), Decimal(1_100_000), Decimal(1_000_000))
    findings, _ = apply_history((), [line], short, cfg)
    assert findings == ()
    assert consecutive_runs(history, ("syn-dev-h-1", "Cloud Run"), FindingType.TEMUAN_NAIK) == 2


def test_l4_old_item_flat_gets_stable_note(syn):
    assert any("syn-dev-f-1 — Compute Engine" in n and "stabil" in n for n in syn.history_notes)


def test_l4_known_drop_still_low_not_reflagged(cfg, history):
    f = Finding("syn-dev-i-1", "Cloud SQL", FindingType.PENURUNAN_BESAR, Confidence.NORMAL,
                Decimal(600_000), Decimal(1_400_000))
    line = Line(("syn-dev-i-1", "Cloud SQL"), f.cur, f.prior)
    findings, notes = apply_history((f,), [line], history, cfg)
    assert findings == ()
    assert any("sudah diketahui" in n for n in notes)


def test_l4_known_drop_note_in_run(syn):
    assert not any(f.project_id == "syn-dev-i-1" for f in syn.findings)
    assert any("syn-dev-i-1 — Cloud SQL" in n and "sudah diketahui" in n for n in syn.history_notes)


# --- L5 legacy JSON import + gap ---------------------------------------------
def test_l5_import_synthetic_legacy_json(history):
    assert len(history) == 3 and all(isinstance(e, HistoryEntry) for e in history)
    assert history[-1].period_end == date(2026, 10, 28)  # newest last
    rows = to_findings_rows(history)
    assert len(rows) == 1 + 2 + 5
    r = rows[-1]
    assert r["mode"] == "legacy14" and r["type"] == "watchlist" and r["confidence"] is None
    assert r["finding_key"] == make_finding_key("syn-dev-g-1", "Cloud Storage", FindingType.WATCHLIST)
    assert {"run_id", "period_start", "project_id", "service", "cur", "prior", "pct_change", "note"} <= set(r)


def test_l5_fixture_is_labelled_synthetic():
    assert "SYNTHETIC" in json.loads(HISTORY_JSON.read_text(encoding="utf-8"))["_comment"]


def _doc(**over):
    base = json.loads(HISTORY_JSON.read_text(encoding="utf-8"))
    base.update(over)
    return base


@pytest.mark.parametrize(
    "doc",
    [
        _doc(schema_version=2),
        _doc(history="x"),
        _doc(history=_doc()["history"] * 3),  # 9 entries > 6
        _doc(history=list(reversed(_doc()["history"]))),  # not newest-last
    ],
)
def test_l5_rejects_invalid_documents(doc):
    with pytest.raises(HistoryError):
        parse_legacy_history(doc)


def test_l5_rejects_unknown_item_type():
    doc = _doc()
    doc["history"][0]["items"][0]["type"] = "spike"
    with pytest.raises(HistoryError, match="unknown type"):
        parse_legacy_history(doc)


def test_l5_gap_detected(syn, history):
    note = gap_note(history, syn.periods.current)
    assert "29 Oktober 2026 s.d. 31 Oktober 2026" in note and "3 hari" in note
    assert note in syn.methodology_notes


def test_l5_gap_like_prototype_15_17_oct(history):
    last = dataclasses.replace(history[-1], period_start=date(2026, 10, 1), period_end=date(2026, 10, 14))
    note = gap_note([last], Period(date(2026, 10, 18), date(2026, 10, 31)))
    assert "15 Oktober 2026 s.d. 17 Oktober 2026" in note


def test_l5_no_gap_when_contiguous_and_overlap_noted(history):
    assert gap_note(history, Period(date(2026, 10, 29), date(2026, 11, 11))) is None
    assert "tumpang tindih" in gap_note(history, Period(date(2026, 10, 20), date(2026, 11, 2)))
    assert gap_note((), Period(date(2026, 11, 1), date(2026, 11, 14))) is None


# --- L6 project overview + "Lainnya" -----------------------------------------
def test_l6_overview_folds_rest_and_reconciles(oct_result):
    ov = oct_result.project_overview
    assert len(ov) == 13 and ov[-1].key == ("Lainnya (25 project)",)
    assert sum(ln.cur for ln in ov) == oct_result.total.cur
    assert sum(ln.prior for ln in ov) == oct_result.total.prior
    assert "Lainnya (25 project)" in oct_result.plain_text


def test_l6_no_fold_for_small_list():
    lines = [Line((f"p{i}",), Decimal(i), Decimal(0)) for i in range(13)]
    assert len(analytics.project_overview(lines, 12)) == 13
    assert not any("Lainnya" in ln.key[0] for ln in analytics.project_overview(lines, 12))


def test_l6_broken_overview_fails_reconciliation(oct_result, cfg):
    ov = list(oct_result.project_overview)
    ov[-1] = Line(ov[-1].key, ov[-1].cur + 1000, ov[-1].prior)
    broken = dataclasses.replace(oct_result, project_overview=tuple(ov))
    assert "reconciliation" in validate_run(broken, cfg).codes()


# --- L7 service breakdown + SKU drill-down ------------------------------------
def test_l7_service_breakdown_for_top3(syn):
    assert tuple(syn.service_breakdown) == S.EXPECTED_TOP3
    svc = {ln.key[0]: ln for ln in syn.service_breakdown["syn-prod-b-1"]}
    assert svc["Cloud SQL"].cur == 800_000 and svc["Cloud SQL"].prior == 2_000_000


def test_l7_sku_drilldown_new_cost_and_drop(syn):
    new = syn.sku_drilldowns[("syn-prod-a-1", "BigQuery")]
    assert [ln.key[0] for ln in new] == ["Analysis", "Active Logical Storage"]
    drop = syn.sku_drilldowns[("syn-prod-b-1", "Cloud SQL")]
    assert drop[0].key == ("vCPU",) and drop[0].delta == -800_000
    assert _by_label(syn)["syn-prod-b-1 — Cloud SQL"].driver_sku == "vCPU"
    # Plain spikes get no drill-down table (driver SKU only).
    assert ("syn-prod-c-1", "Cloud Run") not in syn.sku_drilldowns
    assert "Active Logical Storage" in syn.plain_text


# --- L8 watchlist outside top 3 -----------------------------------------------
def test_l8_watchlist_items(syn):
    f = _by_label(syn)
    assert f["syn-dev-e-1 — Compute Engine"].rule == "swing"
    assert f["syn-dev-f-1 — Pub/Sub"].type is FindingType.WATCHLIST_NEW_COST
    g = f["syn-dev-g-1 — Cloud Storage"]
    assert g.rule == "storage_without_compute" and "lifecycle policy" in g.note
    watch = [x for x in syn.findings if x.type in (FindingType.WATCHLIST, FindingType.WATCHLIST_NEW_COST)]
    assert not any(x.project_id in S.EXPECTED_TOP3 for x in watch)


def test_l8_storage_with_compute_growth_not_flagged(cfg):
    spec_c = {("q", "Compute Engine", "x"): 700_000, ("q", "Cloud Storage", "s"): 400_000,
              ("big", "Compute Engine", "x"): 50_000_000}
    spec_p = {("q", "Compute Engine", "x"): 500_000, ("q", "Cloud Storage", "s"): 300_000,
              ("big", "Compute Engine", "x"): 50_000_000}
    cur, pri = _agg(_rows(spec_c, D_CUR), _rows(spec_p, D_PRI))
    assert not any(f.rule == "storage_without_compute" for f in classify(cur, pri, cfg))


def test_l8_watchlist_does_not_change_status(syn, cfg):
    rising = [f for f in syn.findings if f.type is FindingType.TEMUAN_NAIK]
    assert derive_status(rising, cfg) is derive_status(syn.findings, cfg)


# --- L9 project.name change ---------------------------------------------------
def test_l9_rename_one_row_one_note(syn):
    assert [ln.key for ln in syn.views["project"]].count(("syn-prod-a-1",)) == 1
    notes = [n for n in syn.methodology_notes if "project.name berubah" in n]
    assert len(notes) == 1 and "syn-prod-a-1" in notes[0]


def test_l9_no_note_without_rename(oct_result):
    assert not any("project.name" in n for n in oct_result.methodology_notes)


# --- L10 null project + Vertex AI Search --------------------------------------
def test_l10_null_project_vertex_ai_search_note(syn):
    assert any("Vertex AI Search" in n and "Gemini Enterprise" in n for n in syn.methodology_notes)
    assert ("(unattributed)",) in [ln.key for ln in syn.views["project"]]


def test_l10_no_note_for_other_null_rows(cfg):
    cur = analytics.aggregate([CostRow(D_CUR, None, "Cloud Storage", Decimal(5))])
    assert analytics.null_project_hint_note(cur, analytics.aggregate([]), cfg.null_project_hint_services) is None


# --- L11 subject + plain text -------------------------------------------------
def test_l11_subject_format(legacy_oct, syn):
    assert legacy_oct.subject == (
        "[GCP Billing Check] Status: Ada Indikasi Anomali — 18 Oktober 2026 s.d. 31 Oktober 2026"
    )
    assert syn.subject == build_subject(syn)
    assert syn.subject.endswith("Status: Perlu Perhatian — 1 November 2026 s.d. 14 November 2026")
    assert format_date_id(date(2027, 1, 1)) == "1 Januari 2027"


def test_l11_plain_text_has_required_parts(legacy_oct, cfg):
    text = legacy_oct.plain_text
    for part in ("Status: Ada Indikasi Anomali", "RINGKASAN", "IKHTISAR PROJECT", "RINCIAN SERVICE",
                 "TEMUAN YANG DITANDAI", "Rp47.587.313", "Rp44.416.052", "+7,14%"):
        assert part in text, part
    assert text == build_plain_text(legacy_oct, cfg)
    assert "<" not in text  # plain text, no markup


# --- L12 failed self-check is never sent --------------------------------------
class _BadProvider:
    def generate(self, result, cfg):
        return "Total biaya Rp99.999.999."


def test_l12_failed_self_check_routes_to_review(cfg):
    r = orchestrator.run("legacy14", oct2026.AS_OF, InMemoryCostSource(oct2026.build_rows()), cfg,
                         narrative_provider=_BadProvider())
    assert r.route == "review" and not orchestrator.is_dispatchable(r)
    assert "unknown_amount" in r.validation.codes()


def test_l12_tampered_plain_text_fails_gate(legacy_oct, cfg):
    bad = dataclasses.replace(legacy_oct, plain_text=legacy_oct.plain_text + "\nPenghematan Rp1.234.567.\n")
    assert "plain_text_unknown_amount" in validate_run(bad, cfg).codes()


def test_l12_no_force_send_option():
    params = set(inspect.signature(orchestrator.run).parameters)
    assert not any("force" in p or "skip" in p for p in params)
    assert orchestrator.is_dispatchable.__doc__ and "no override" in orchestrator.is_dispatchable.__doc__


def test_l12_valid_runs_are_dispatchable(legacy_oct, syn):
    assert orchestrator.is_dispatchable(legacy_oct)
    assert syn.validation.ok, syn.validation.violations
    assert orchestrator.is_dispatchable(syn)


# --- L13 "Project — Service" ---------------------------------------------------
def test_l13_every_finding_names_project_and_service(syn, legacy_oct):
    for r in (syn, legacy_oct):
        for f in r.findings:
            assert f.service_name != "*" and " — " in f.label
            assert f.label in r.plain_text
    digi = next(f for f in legacy_oct.findings if f.project_id == "bss-prod-digivisit-1")
    assert digi.label == "bss-prod-digivisit-1 — (synthetic remainder)"


def test_l13_validator_rejects_missing_label():
    bad = Finding("p", "*", FindingType.WATCHLIST, Confidence.NORMAL, Decimal(1), Decimal(0))
    empty = Finding("", "S", FindingType.WATCHLIST, Confidence.NORMAL, Decimal(1), Decimal(0))
    assert len(check_finding_labels([bad, empty])) == 2


def test_l13_narrative_must_name_each_counted_finding(legacy_oct, cfg):
    text = legacy_oct.narrative.replace("bss-prod-pdaja-1 — Maps API", "Maps API")
    assert "finding_not_named" in validate_run(legacy_oct, cfg, narrative=text).codes()
