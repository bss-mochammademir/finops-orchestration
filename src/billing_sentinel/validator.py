"""Quality gate (ABB A05). A failing report is routed to internal review, never sent.

Checks:
1. every amount/percentage in narrative text is one the code computed
   (``Rp`` amounts must match exactly; shorthand ``ribu/juta/miliar`` must match a
   computed amount within ``shorthand_tolerance_units`` of its displayed precision);
2. no invoice-approval wording (status is separate from approval, doc 11 F-6);
3. reconciliation of the two views: sum(category) == sum(project) == total,
   within an explicit rounding tolerance;
4. status is consistent with the findings;
5. ``finding_events``: ``acknowledged_normal`` requires ``expires_on``;
6. last-day lag detection (lessons §8.3) produces an automatic note.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal

from .classify import derive_status
from .config import Config
from .domain import (
    ZERO,
    FindingEvent,
    FindingState,
    Line,
    Period,
    RunResult,
    ValidationReport,
    Violation,
)
from .money import format_idr, parse_full_amounts, parse_percentages, parse_shorthand, round_idr

APPROVAL_PHRASE_RE = re.compile(r"siap\s*(di[\s-]?)?(setujui|approve)", re.IGNORECASE)


# --------------------------------------------------------------------------- numbers
def computed_amounts(result: RunResult) -> set[Decimal]:
    """All amounts (absolute, rounded to whole Rupiah) the code computed for a run."""
    vals: list[Decimal] = []
    lines: list[Line] = [result.total]
    if result.secondary_total is not None:
        lines.append(result.secondary_total)
    for view_lines in result.views.values():
        lines.extend(view_lines)
    for ln in lines:
        vals += [ln.cur, ln.prior, ln.delta]
    for f in result.findings:
        vals += [f.cur, f.prior, f.delta]
    vals += [result.daily_avg_cur, result.daily_avg_prior, result.daily_avg_cur - result.daily_avg_prior]
    return {abs(round_idr(v)) for v in vals}


def computed_percentages(result: RunResult) -> list[Decimal]:
    pcts: list[Decimal | None] = [result.total.pct_change]
    if result.secondary_total is not None:
        pcts.append(result.secondary_total.pct_change)
    for view_lines in result.views.values():
        pcts += [ln.pct_change for ln in view_lines]
    pcts += [f.pct_change for f in result.findings]
    if result.daily_avg_prior:
        pcts.append((result.daily_avg_cur - result.daily_avg_prior) / abs(result.daily_avg_prior) * 100)
    if result.coverage_adr003 is not None:
        pcts.append(result.coverage_adr003 * 100)
    return [p for p in pcts if p is not None]


def check_narrative_numbers(
    text: str,
    amounts: Iterable[Decimal],
    percentages: Iterable[Decimal] = (),
    shorthand_tolerance_units: Decimal = Decimal(1),
) -> list[Violation]:
    """Narrative numbers must be a subset of computed numbers (lessons §8.1, §8.9)."""
    allowed = {abs(round_idr(a)) for a in amounts}
    pcts = list(percentages)
    out: list[Violation] = []
    for sh in parse_shorthand(text):
        if not any(sh.matches(a, shorthand_tolerance_units) for a in allowed):
            out.append(Violation("shorthand_mismatch", f"'{sh.text}' does not match any computed amount"))
    for full in parse_full_amounts(text):
        if round_idr(full.value) not in allowed:
            out.append(Violation("unknown_amount", f"'{full.text}' is not a computed amount"))
    for p in parse_percentages(text):
        if not any(p.matches(c) for c in pcts):
            out.append(Violation("unknown_percentage", f"'{p.text}' is not a computed percentage"))
    return out


def check_no_approval_wording(text: str) -> list[Violation]:
    if APPROVAL_PHRASE_RE.search(text):
        return [Violation("approval_wording", "anomaly status must not be phrased as invoice approval")]
    return []


# --------------------------------------------------------------------------- reconciliation
def check_reconciliation(result: RunResult, tolerance_idr: Decimal) -> list[Violation]:
    """sum(category view) == sum(project view) == total, for current and prior.

    Two checks with the same explicit tolerance:
    - raw (unrounded) sums: must agree up to ``tolerance_idr`` (expected exact);
    - displayed sums: sum of per-row values rounded to whole Rupiah vs the rounded
      total. Per-row ROUND() can drift by up to 0.5 x rows; the prototype allowed
      +/-40 (default ``[reconciliation] tolerance_idr``).
    """
    out: list[Violation] = []
    for attr in ("cur", "prior"):
        total = getattr(result.total, attr)
        for view in ("category", "project"):
            lines = result.views.get(view, ())
            raw = sum((getattr(ln, attr) for ln in lines), ZERO)
            shown = sum((round_idr(getattr(ln, attr)) for ln in lines), ZERO)
            if abs(raw - total) > tolerance_idr:
                out.append(
                    Violation("reconciliation", f"{view}.{attr} raw sum {raw} != total {total}")
                )
            if abs(shown - round_idr(total)) > tolerance_idr:
                out.append(
                    Violation(
                        "reconciliation_rounding",
                        f"{view}.{attr} displayed sum {format_idr(shown)} vs total "
                        f"{format_idr(total)} exceeds tolerance Rp{tolerance_idr}",
                    )
                )
    return out


# --------------------------------------------------------------------------- status
def check_status(result: RunResult, cfg: Config) -> list[Violation]:
    expected = derive_status(result.findings, cfg)
    out: list[Violation] = []
    if expected is not result.status:
        out.append(Violation("status_inconsistent", f"status {result.status.value} but findings imply {expected.value}"))
    if result.status_color != cfg.status_color(result.status):
        out.append(Violation("status_color", f"colour {result.status_color} does not match {result.status.value}"))
    return out


# --------------------------------------------------------------------------- finding events
def check_finding_events(events: Iterable[FindingEvent]) -> list[Violation]:
    """``acknowledged_normal`` without ``expires_on`` is rejected (no permanent silencing)."""
    out: list[Violation] = []
    for ev in events:
        if ev.state is FindingState.ACKNOWLEDGED_NORMAL and ev.expires_on is None:
            out.append(
                Violation("ack_without_expiry", f"finding {ev.finding_key}: acknowledged_normal requires expires_on")
            )
        if ev.expires_on is not None and ev.expires_on < ev.event_date:
            out.append(Violation("ack_expiry_before_event", f"finding {ev.finding_key}: expires_on before event"))
    return out


# --------------------------------------------------------------------------- lag
def last_day_lag_note(daily: Mapping[date, Decimal], period: Period, ratio: Decimal) -> str | None:
    """Note when the last day of ``period`` is below ``ratio`` x median of the other days.

    Missing days count as zero. The median excludes the last day itself. Returns
    ``None`` if there are fewer than two days or the median is not positive.
    """
    days = period.dates()
    if len(days) < 2:
        return None
    last = daily.get(days[-1], ZERO)
    median = Decimal(statistics.median([daily.get(d, ZERO) for d in days[:-1]]))
    if median <= 0 or last >= median * ratio:
        return None
    return (
        f"Data {days[-1].isoformat()} kemungkinan belum lengkap (lag export billing): "
        f"{format_idr(last)} vs median harian {format_idr(median)}; "
        "total periode berjalan kemungkinan sedikit understated."
    )


# --------------------------------------------------------------------------- entry point
def validate_run(
    result: RunResult,
    cfg: Config,
    narrative: str | None = None,
    events: Iterable[FindingEvent] = (),
) -> ValidationReport:
    text = result.narrative if narrative is None else narrative
    violations: list[Violation] = []
    violations += check_narrative_numbers(
        text, computed_amounts(result), computed_percentages(result), cfg.shorthand_tolerance_units
    )
    violations += check_no_approval_wording(text)
    violations += check_reconciliation(result, cfg.reconciliation_tolerance_idr)
    violations += check_status(result, cfg)
    violations += check_finding_events(events)
    return ValidationReport(tuple(violations))
