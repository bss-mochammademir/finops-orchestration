"""Half-month periods (1-15, 16-EOM) and their comparison periods.

Rationale (doc 11 F-8, lessons §8.2): a rolling 14-vs-14-day window produces
repeated false positives on monthly billing cycles (free-tier quota exhaustion,
sustained use discounts). The primary comparison is therefore the *same half of
the previous month* (MoM); the immediately preceding half is kept as a
secondary comparison. Halves have different lengths (13-16 days), so callers
must also report daily averages.

``legacy14`` reproduces the legacy routine window (14 days ending yesterday vs
the 14 days before) for the parallel run only (WP1b, L1).
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal

from .domain import Mode, Period, PeriodSet


def _eom(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _prev_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def half_month_of(d: date) -> Period:
    """The full half-month (1-15 or 16-EOM) containing ``d``."""
    if d.day <= 15:
        return Period(date(d.year, d.month, 1), date(d.year, d.month, 15))
    return Period(date(d.year, d.month, 16), _eom(d.year, d.month))


def is_full_half(p: Period) -> bool:
    return half_month_of(p.start) == p


def previous_half(p: Period) -> Period:
    """The full half-month immediately before the half containing ``p.start``."""
    return half_month_of(half_month_of(p.start).start - timedelta(days=1))


def same_half_previous_month(p: Period) -> Period:
    """MoM comparison period.

    For a full half the result is the full same half of the previous month
    (e.g. 2026-11-16..30 -> 2026-10-16..31). For a partial (half-to-date)
    period, the same day offsets are used, clipped to the end of that half.
    """
    y, m = _prev_month(p.start.year, p.start.month)
    if p.start.day <= 15:
        target = Period(date(y, m, 1), date(y, m, 15))
    else:
        target = Period(date(y, m, 16), _eom(y, m))
    if is_full_half(p):
        return target
    offset_start = (p.start - half_month_of(p.start).start).days
    start = min(target.start + timedelta(days=offset_start), target.end)
    end = min(start + timedelta(days=p.days - 1), target.end)
    return Period(start, end)


def report_period(as_of: date) -> Period:
    """Last *completed* half-month strictly before the half containing ``as_of``.

    Example: as_of 2026-12-03 -> 2026-11-16..2026-11-30.
    """
    return previous_half(half_month_of(as_of))


def triage_period(as_of: date) -> Period:
    """Half-month-to-date ending the day before ``as_of``.

    ASSUMPTION (to be confirmed by the report owner): weekly triage looks at the
    running half-month up to yesterday, compared MoM with the same day offsets.
    On the 1st/16th this equals the just-completed half.
    """
    yesterday = as_of - timedelta(days=1)
    half = half_month_of(yesterday)
    return Period(half.start, yesterday)


LEGACY_WINDOW_DAYS = 14


def legacy14_periods(as_of: date, days: int = LEGACY_WINDOW_DAYS) -> PeriodSet:
    """Legacy routine window (L1), used only for the parallel run.

    Current = the ``days`` days ending *yesterday* (by ``usage_start_time``, i.e.
    ``charge_date``); comparison = the ``days`` days immediately before. There is
    no secondary comparison. Example: as_of 2026-11-01 -> 2026-10-18..31 vs
    2026-10-04..17.
    """
    end = as_of - timedelta(days=1)
    current = Period(end - timedelta(days=days - 1), end)
    prior_end = current.start - timedelta(days=1)
    prior = Period(prior_end - timedelta(days=days - 1), prior_end)
    return PeriodSet(current=current, mom=prior, prior_half=None)


def resolve_periods(mode: Mode | str, as_of: date) -> PeriodSet:
    mode = Mode(mode)
    if mode is Mode.LEGACY14:
        return legacy14_periods(as_of)
    current = report_period(as_of) if mode is Mode.REPORT else triage_period(as_of)
    return PeriodSet(
        current=current,
        mom=same_half_previous_month(current),
        prior_half=previous_half(current),
    )


def daily_average(amount: Decimal, period: Period) -> Decimal:
    """Average per day, unrounded."""
    return amount / Decimal(period.days)

