"""Regression: legacy run 18-31 Oct 2026 (spec §2 IN.3)."""

from decimal import Decimal

from billing_sentinel.classify import border_color, derive_status, is_large_spike
from billing_sentinel.domain import Confidence, FindingType, Status
from billing_sentinel.money import format_idr, format_pct, round_idr
from fixtures import oct2026


def test_raw_proj_is_verbatim_shape():
    assert len(oct2026.RAW_PROJ) == 37
    assert oct2026.RAW_TOTAL == (47587313, 44416052)


def test_totals_and_change(oct_result, cfg):
    assert format_idr(oct_result.total.cur) == "Rp47.587.313"
    assert format_idr(oct_result.total.prior) == "Rp44.416.052"
    assert format_pct(oct_result.total.pct_change, cfg.pct_decimals) == "+7,14%"


def test_unrounded_totals_exact(oct_result):
    assert oct_result.total.cur == Decimal("47587313")
    assert oct_result.total.prior == Decimal("44416052")


def test_per_project_values_round_to_raw_proj(oct_result):
    by_project = {ln.key[0]: ln for ln in oct_result.views["project"]}
    assert set(by_project) == set(oct2026.RAW_PROJ)
    for project, (cur, prior) in oct2026.RAW_PROJ.items():
        assert round_idr(by_project[project].cur) == cur, project
        assert round_idr(by_project[project].prior) == prior, project


def test_rounding_tolerance_is_explicit(oct_result, cfg):
    """Displayed per-project sums differ from the ROLLUP total by +3 / +1 (prototype: <= 40)."""
    shown_cur = sum(round_idr(ln.cur) for ln in oct_result.views["project"])
    shown_prior = sum(round_idr(ln.prior) for ln in oct_result.views["project"])
    assert shown_cur - oct2026.RAW_TOTAL[0] == 3
    assert shown_prior - oct2026.RAW_TOTAL[1] == 1
    n = len(oct_result.views["project"])
    assert abs(shown_cur - oct2026.RAW_TOTAL[0]) <= Decimal("0.5") * n <= cfg.reconciliation_tolerance_idr
    assert cfg.reconciliation_tolerance_idr == Decimal("40")


def test_top3(oct_result):
    assert oct_result.top_projects == oct2026.EXPECTED_TOP3


def test_findings_match_prototype(oct_result, cfg):
    counted = {
        (f.project_id, f.service_name): (f.type.value, f.confidence.value)
        for f in oct_result.findings
        if f.type is FindingType.TEMUAN_NAIK
    }
    assert counted == oct2026.EXPECTED_FINDINGS
    borders = sorted(border_color(f, cfg) for f in oct_result.findings if f.type is FindingType.TEMUAN_NAIK)
    assert borders == ["#9aa5b1", "#f9a825", "#f9a825", "#f9a825"]  # 3 amber + 1 grey


def test_maps_is_large_spike(oct_result, cfg):
    maps = next(f for f in oct_result.findings if f.service_name == "Maps API")
    assert maps.pct_change > 100 and maps.delta > 1_000_000
    assert is_large_spike(maps, cfg)
    assert maps.driver_sku == "Dynamic Maps"
    assert maps.app_category_code == "ac_023"
    others = [f for f in oct_result.findings if f is not maps]
    assert not any(is_large_spike(f, cfg) for f in others)


def test_cloud_logging_driver_is_new_sku(oct_result):
    f = next(f for f in oct_result.findings if f.service_name == "Cloud Logging")
    assert f.driver_sku == "Log Storage cost"


def test_new_project_is_watchlist_not_counted(oct_result):
    digi = [f for f in oct_result.findings if f.project_id == "bss-prod-digivisit-1"]
    assert [f.type for f in digi] == [FindingType.WATCHLIST_NEW_COST]


def test_status_anomali(oct_result, cfg):
    assert oct_result.status is Status.ANOMALI
    assert oct_result.status_color == "#c62828"
    assert derive_status(oct_result.findings, cfg) is Status.ANOMALI


def test_status_anomali_even_without_large_spike(oct_result, cfg):
    """3 amber alone already reach the >= 3 rule."""
    normal = [f for f in oct_result.findings if f.type is FindingType.TEMUAN_NAIK and f.confidence is Confidence.NORMAL]
    assert len(normal) == 3


def test_validation_passes_and_routes_to_dispatch(oct_result):
    assert oct_result.validation.ok, oct_result.validation.violations
    assert oct_result.route == "dispatch"


def test_narrative_restates_regression_numbers(oct_result):
    text = oct_result.narrative
    assert "Rp47.587.313" in text and "Rp44.416.052" in text and "+7,14%" in text
    assert "siap disetujui" not in text.lower()


def test_coverage_counts_only_labelled(oct_result):
    mapped = sum(v[0] for p, v in oct2026.RAW_PROJ.items() if p in oct2026.CATEGORY_LABELS)
    expected = Decimal(mapped) / Decimal(oct2026.RAW_TOTAL[0])
    assert abs(oct_result.coverage_adr003 - expected) < Decimal("0.000001")
    assert oct_result.coverage_adr003 < 1
    assert "bss-prod-notification-1" in oct_result.unmapped_projects
    assert "bss-prod-ekyc-2" not in oct_result.unmapped_projects
