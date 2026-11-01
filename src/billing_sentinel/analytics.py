"""Deterministic aggregation over ``CostRow`` (one fact base, several views).

Rules encoded here:
- net cost = cost + credits (``CostRow.net_cost``);
- grouping is always by ``project_id``, never by project name (lessons §8.4);
- a null/empty project id is reported as ``(unattributed)`` (lessons §8.5);
- a missing/empty ``application_category`` label is ``UNMAPPED`` (doc 11 F-2).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .domain import UNATTRIBUTED_PROJECT, UNMAPPED, ZERO, CostRow, Line

VIEWS = ("project", "service", "category", "project_service", "project_service_sku")


def project_key(row: CostRow) -> str:
    pid = (row.project_id or "").strip()
    return pid or UNATTRIBUTED_PROJECT


def category_key(row: CostRow) -> str:
    code = (row.app_category_code or "").strip()
    return code or UNMAPPED


def _keys(row: CostRow) -> dict[str, tuple[str, ...]]:
    p = project_key(row)
    return {
        "project": (p,),
        "service": (row.service_name,),
        "category": (category_key(row),),
        "project_service": (p, row.service_name),
        "project_service_sku": (p, row.service_name, row.sku_name),
    }


@dataclass
class Aggregate:
    total: Decimal = ZERO
    views: dict[str, dict[tuple[str, ...], Decimal]] = field(
        default_factory=lambda: {v: defaultdict(lambda: ZERO) for v in VIEWS}
    )
    daily: dict[date, Decimal] = field(default_factory=lambda: defaultdict(lambda: ZERO))
    project_category: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))


def aggregate(rows: Iterable[CostRow]) -> Aggregate:
    agg = Aggregate()
    for row in rows:
        net = row.net_cost
        agg.total += net
        agg.daily[row.charge_date] += net
        for view, key in _keys(row).items():
            agg.views[view][key] += net
        agg.project_category[project_key(row)].add(category_key(row))
    return agg


def compare(cur: Aggregate, prior: Aggregate, view: str) -> tuple[Line, ...]:
    """Lines for ``view``, sorted by current cost desc then key (deterministic)."""
    keys = set(cur.views[view]) | set(prior.views[view])
    lines = [Line(k, cur.views[view].get(k, ZERO), prior.views[view].get(k, ZERO)) for k in keys]
    return tuple(sorted(lines, key=lambda ln: (-ln.cur, ln.key)))


def total_line(cur: Aggregate, prior: Aggregate) -> Line:
    return Line(("TOTAL",), cur.total, prior.total)


def top_projects(lines: Iterable[Line], n: int) -> tuple[str, ...]:
    ranked = sorted(lines, key=lambda ln: (-ln.cur, ln.key))
    return tuple(ln.key[0] for ln in ranked[:n])


def project_category_code(agg: Aggregate, project_id: str) -> str:
    """Category of a project in the current period.

    If a project's label changed mid-period it carries several codes; the
    result is then the sorted codes joined by ``|`` so that the ambiguity stays
    visible rather than being silently resolved.
    """
    codes = agg.project_category.get(project_id) or {UNMAPPED}
    return "|".join(sorted(codes))
