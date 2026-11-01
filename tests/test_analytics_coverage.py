from datetime import date
from decimal import Decimal

from billing_sentinel import analytics
from billing_sentinel.coverage import coverage_from_aggregate, unmapped_projects
from billing_sentinel.domain import UNATTRIBUTED_PROJECT, UNMAPPED, CostRow

D = date(2026, 11, 20)


def row(pid, amount, credits=0, code=None, name=None, svc="Compute Engine"):
    return CostRow(D, pid, svc, Decimal(amount), Decimal(credits), app_category_code=code, project_name=name)


def test_net_cost_is_cost_plus_credits():
    agg = analytics.aggregate([row("a", 1000, -250)])
    assert agg.total == Decimal(750)


def test_group_by_project_id_not_name():
    rows = [
        row("bss-prod-x-1", 100, name="Old Name"),
        row("bss-prod-x-1", 50, name="New Name"),
        row("bss-prod-y-1", 10, name="Old Name"),
    ]
    agg = analytics.aggregate(rows)
    assert dict(agg.views["project"]) == {("bss-prod-x-1",): Decimal(150), ("bss-prod-y-1",): Decimal(10)}


def test_null_project_is_unattributed():
    agg = analytics.aggregate([row(None, 5, svc="Vertex AI Search"), row("", 7)])
    assert dict(agg.views["project"]) == {(UNATTRIBUTED_PROJECT,): Decimal(12)}


def test_missing_label_is_unmapped():
    agg = analytics.aggregate([row("a", 10), row("b", 20, code="  "), row("c", 30, code="ac_050")])
    assert dict(agg.views["category"]) == {(UNMAPPED,): Decimal(30), ("ac_050",): Decimal(30)}


def test_coverage_strict_unmapped_not_attributed():
    rows = [row("a", 600, code="ac_050"), row("b", 300), row(None, 100)]
    agg = analytics.aggregate(rows)
    assert coverage_from_aggregate(agg) == Decimal("0.6")
    assert unmapped_projects(rows) == (UNATTRIBUTED_PROJECT, "b")


def test_coverage_explicit_ac_046_counts_as_attributed():
    agg = analytics.aggregate([row("a", 50, code="ac_046"), row("b", 50)])
    assert coverage_from_aggregate(agg) == Decimal("0.5")


def test_coverage_none_when_total_not_positive():
    assert coverage_from_aggregate(analytics.aggregate([])) is None


def test_label_at_usage_time_kept_per_row():
    """A project relabelled mid-period keeps both codes; the ambiguity stays visible."""
    rows = [row("a", 10, code="ac_023"), row("a", 5, code="ac_050")]
    agg = analytics.aggregate(rows)
    assert dict(agg.views["category"]) == {("ac_023",): Decimal(10), ("ac_050",): Decimal(5)}
    assert analytics.project_category_code(agg, "a") == "ac_023|ac_050"
