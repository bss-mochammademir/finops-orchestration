"""Strict ADR-003 attribution coverage (C_ADR003).

``C_ADR003 = sum(net_cost where code != UNMAPPED) / sum(net_cost)`` (doc 11 §4).

``UNMAPPED`` is never counted as attributed. ``ac_046`` ("Others / Unassigned")
counts as attributed only because it can only appear here when a human wrote
that label explicitly; the core never defaults to it (closes AMB-06). The final
rule for ``ac_046`` is owned by IT Finance (gate G3).
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from .analytics import Aggregate, category_key, project_key
from .domain import UNMAPPED, ZERO, CostRow


def coverage_from_aggregate(agg: Aggregate) -> Decimal | None:
    """Fraction 0..1 of net cost carrying an ADR-003 label; None if total <= 0."""
    if agg.total <= 0:
        return None
    attributed = sum(
        (v for (code,), v in agg.views["category"].items() if code != UNMAPPED), ZERO
    )
    return attributed / agg.total


def unmapped_projects(rows: Iterable[CostRow]) -> tuple[str, ...]:
    """Projects with at least one unlabelled row (shown under "Belum Terpetakan")."""
    return tuple(sorted({project_key(r) for r in rows if category_key(r) == UNMAPPED}))
