"""FinOps scoring engine (ABB A03), kept separate from analytics.

STUB — TODO(WP4): score v0 = ``C_ADR003`` (see ``coverage.py``) + recurring
finding count, stored in ``finops_score`` with ``formula_version='v0-coverage'``.
The PCRI formula is only a *candidate* until IT Finance closes AMB-02; reports
must not show a PCRI score before that (doc 11 F-5, F-11).
"""

from __future__ import annotations

from decimal import Decimal

from .domain import RunResult

FORMULA_VERSION = "v0-coverage"


def score_v0(result: RunResult) -> Decimal:
    """TODO(WP4): compute score v0 once IT Finance agrees the rule (gate G3)."""
    raise NotImplementedError("score_v0 is scheduled for WP4")
