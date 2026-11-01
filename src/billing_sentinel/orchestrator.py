"""Run orchestration (ABB A01): periods -> fetch -> aggregate -> classify -> narrate -> validate.

``run`` is pure with respect to its inputs: no network, no clock, no randomness.
Rendering and dispatch are WP2+/WP3 and are not invoked here.
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Iterable
from datetime import date

from . import analytics, coverage
from .classify import classify, derive_status
from .config import Config
from .domain import FindingEvent, Mode, Period, PeriodSet, RunResult
from .narrative import NarrativeProvider, TemplateNarrativeProvider
from .periods import daily_average, resolve_periods
from .sources import CostSource
from .validator import last_day_lag_note, validate_run


def make_run_id(mode: Mode | str, period: Period, config_version: str) -> str:
    """Deterministic idempotency key for (mode, period, config version).

    A rerun for the same period and config yields the same ``run_id``, which
    the dispatcher (WP2) uses to avoid sending a report twice.
    """
    raw = f"{Mode(mode).value}|{period.start.isoformat()}|{period.end.isoformat()}|{config_version}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def run(
    mode: Mode | str,
    as_of: date,
    source: CostSource,
    config: Config,
    *,
    periods: PeriodSet | None = None,
    narrative_provider: NarrativeProvider | None = None,
    finding_events: Iterable[FindingEvent] = (),
) -> RunResult:
    """Execute one deterministic run.

    ``periods`` overrides the calendar-derived periods (used to replay the
    legacy 14-vs-14-day run in regression tests or for backfills).
    """
    mode = Mode(mode)
    ps = periods or resolve_periods(mode, as_of)

    cur_rows = source.fetch(ps.current.start, ps.current.end)
    mom_rows = source.fetch(ps.mom.start, ps.mom.end)
    cur = analytics.aggregate(cur_rows)
    prior = analytics.aggregate(mom_rows)

    secondary = None
    if ps.prior_half is not None:
        ph = analytics.aggregate(source.fetch(ps.prior_half.start, ps.prior_half.end))
        secondary = analytics.total_line(cur, ph)

    views = {v: analytics.compare(cur, prior, v) for v in ("project", "service", "category", "project_service")}
    findings = classify(cur, prior, config)
    status = derive_status(findings, config)

    notes: list[str] = []
    lag = last_day_lag_note(cur.daily, ps.current, config.lag_ratio)
    if lag:
        notes.append(lag)
    unmapped = coverage.unmapped_projects(cur_rows)
    if unmapped:
        notes.append(f"{len(unmapped)} project belum terpetakan ke ADR-003 (Belum Terpetakan).")
    # TODO(WP2): apply active finding_events (e.g. unexpired acknowledged_normal)
    # to findings history; WP1 only validates the events.

    result = RunResult(
        run_id=make_run_id(mode, ps.current, config.config_version),
        mode=mode,
        as_of=as_of,
        periods=ps,
        config_version=config.config_version,
        total=analytics.total_line(cur, prior),
        views=views,
        findings=findings,
        status=status,
        status_color=config.status_color(status),
        coverage_adr003=coverage.coverage_from_aggregate(cur),
        daily_avg_cur=daily_average(cur.total, ps.current),
        daily_avg_prior=daily_average(prior.total, ps.mom),
        secondary_total=secondary,
        top_projects=analytics.top_projects(views["project"], config.top_n_projects),
        unmapped_projects=unmapped,
        notes=tuple(notes),
    )

    provider = narrative_provider or TemplateNarrativeProvider()
    try:
        text = provider.generate(result, config)
    except Exception as exc:  # noqa: BLE001 - any provider failure degrades gracefully
        # Graceful degradation (D-3): the report still goes out with template text.
        text = TemplateNarrativeProvider().generate(result, config)
        result = dataclasses.replace(
            result, notes=result.notes + (f"Narasi model tidak tersedia ({type(exc).__name__}); dipakai narasi template.",)
        )
    result = dataclasses.replace(result, narrative=text)

    # A failing quality gate routes to internal review, never to recipients (D-2).
    report = validate_run(result, config, events=finding_events)
    return dataclasses.replace(result, validation=report, route="dispatch" if report.ok else "review")
