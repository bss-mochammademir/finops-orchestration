"""Deterministic aggregation over ``CostRow`` (one fact base, several views).

Rules encoded here:
- net cost = cost + credits (``CostRow.net_cost``);
- grouping is always by ``project_id``, never by project name (lessons §8.4);
- a null/empty project id is reported as ``(unattributed)`` (lessons §8.5);
- a missing/empty ``application_category`` label is ``UNMAPPED`` (doc 11 F-2).

Legacy-parity helpers (WP1b): project overview with a "Lainnya (N project)"
line (L6), per-service breakdown and SKU drill-down (L7), and methodology notes
for mid-period project renames (L9) and null-project Vertex AI Search rows (L10).
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
    project_names: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))


def aggregate(rows: Iterable[CostRow]) -> Aggregate:
    agg = Aggregate()
    for row in rows:
        net = row.net_cost
        agg.total += net
        agg.daily[row.charge_date] += net
        for view, key in _keys(row).items():
            agg.views[view][key] += net
        agg.project_category[project_key(row)].add(category_key(row))
        name = (row.project_name or "").strip()
        if name:
            agg.project_names[project_key(row)].add(name)
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


# --------------------------------------------------------------------------- L6
OTHERS_LABEL = "Lainnya ({n} project)"


def project_overview(lines: Iterable[Line], rows: int) -> tuple[Line, ...]:
    """Top ``rows`` project lines plus one folded "Lainnya (N project)" line (L6).

    The folded line is the exact (unrounded) sum of the remaining projects, so
    the overview still reconciles with the grand total. Nothing is folded when
    at most ``rows + 1`` projects exist (a one-project "Lainnya" hides nothing).
    """
    ranked = sorted(lines, key=lambda ln: (-ln.cur, ln.key))
    if len(ranked) <= rows + 1:
        return tuple(ranked)
    head, rest = ranked[:rows], ranked[rows:]
    others = Line(
        (OTHERS_LABEL.format(n=len(rest)),),
        sum((ln.cur for ln in rest), ZERO),
        sum((ln.prior for ln in rest), ZERO),
    )
    return tuple(head) + (others,)


# --------------------------------------------------------------------------- L7
def service_breakdown(cur: Aggregate, prior: Aggregate, projects: Iterable[str]) -> dict[str, tuple[Line, ...]]:
    """Per-service lines (key ``(service,)``) for each requested project (L7)."""
    lines = compare(cur, prior, "project_service")
    return {p: tuple(Line((ln.key[1],), ln.cur, ln.prior) for ln in lines if ln.key[0] == p) for p in projects}


def sku_drilldown(cur: Aggregate, prior: Aggregate, project: str, service: str) -> tuple[Line, ...]:
    """SKU lines (key ``(sku,)``) of one project/service, largest absolute change first (L7)."""
    view = "project_service_sku"
    keys = {k for agg in (cur, prior) for k in agg.views[view] if k[0] == project and k[1] == service}
    lines = [Line((k[2] or "(tanpa SKU)",), cur.views[view].get(k, ZERO), prior.views[view].get(k, ZERO)) for k in keys]
    return tuple(sorted(lines, key=lambda ln: (-abs(ln.delta), ln.key)))


# --------------------------------------------------------------------------- L9, L10
def project_rename_note(cur: Aggregate) -> str | None:
    """One methodology note when any ``project.name`` changed within the period (L9).

    Grouping is by ``project_id`` regardless, so each project keeps one row.
    """
    renamed = sorted(p for p, names in cur.project_names.items() if len(names) > 1)
    if not renamed:
        return None
    return (
        f"Catatan metodologi: project.name berubah di tengah periode untuk {len(renamed)} project "
        f"({', '.join(renamed)}); angka tetap dikelompokkan per project.id sehingga tiap project tetap satu baris."
    )


def null_project_hint_note(cur: Aggregate, prior: Aggregate, hint_services: Iterable[str]) -> str | None:
    """Note when a row without ``project.id`` carries e.g. Vertex AI Search (L10)."""
    hints = [h.lower() for h in hint_services]
    found: set[str] = set()
    for agg in (cur, prior):
        for (project, service), amount in agg.views["project_service"].items():
            if project == UNATTRIBUTED_PROJECT and amount != 0 and any(h in service.lower() for h in hints):
                found.add(service)
    if not found:
        return None
    return (
        f"Catatan metodologi: baris tanpa project.id ({UNATTRIBUTED_PROJECT}) memuat {', '.join(sorted(found))}; "
        "kemungkinan terkait Gemini Enterprise (perlu konfirmasi pemilik layanan)."
    )
