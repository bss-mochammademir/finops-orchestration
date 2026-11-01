"""Half-month periods, MoM comparison and daily averages (spec §2 IN.5)."""

from datetime import date
from decimal import Decimal

from billing_sentinel.domain import Mode, Period
from billing_sentinel.periods import (
    daily_average,
    half_month_of,
    report_period,
    resolve_periods,
    same_half_previous_month,
    triage_period,
)


def test_report_period_for_2026_12_03():
    ps = resolve_periods("report", date(2026, 12, 3))
    assert ps.current == Period(date(2026, 11, 16), date(2026, 11, 30))
    assert ps.mom == Period(date(2026, 10, 16), date(2026, 10, 31))
    assert ps.prior_half == Period(date(2026, 11, 1), date(2026, 11, 15))
    assert (ps.current.days, ps.mom.days) == (15, 16)


def test_report_period_first_half_and_year_boundary():
    assert report_period(date(2026, 12, 18)) == Period(date(2026, 12, 1), date(2026, 12, 15))
    ps = resolve_periods(Mode.REPORT, date(2027, 1, 3))
    assert ps.current == Period(date(2026, 12, 16), date(2026, 12, 31))
    assert ps.mom == Period(date(2026, 11, 16), date(2026, 11, 30))


def test_february_halves():
    assert half_month_of(date(2027, 2, 20)) == Period(date(2027, 2, 16), date(2027, 2, 28))
    assert same_half_previous_month(Period(date(2027, 3, 16), date(2027, 3, 31))) == Period(
        date(2027, 2, 16), date(2027, 2, 28)
    )


def test_triage_half_to_date_and_mom_offsets():
    ps = resolve_periods("triage", date(2026, 11, 23))  # Monday
    assert ps.current == Period(date(2026, 11, 16), date(2026, 11, 22))
    assert ps.mom == Period(date(2026, 10, 16), date(2026, 10, 22))
    assert triage_period(date(2026, 12, 1)) == Period(date(2026, 11, 16), date(2026, 11, 30))


def test_daily_average_handles_different_lengths():
    cur = Period(date(2026, 11, 16), date(2026, 11, 30))
    prior = Period(date(2026, 10, 16), date(2026, 10, 31))
    assert daily_average(Decimal(1_500_000), cur) == Decimal(100_000)
    assert daily_average(Decimal(1_600_000), prior) == Decimal(100_000)
