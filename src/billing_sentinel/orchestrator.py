"""Run orchestration (ABB A01): periods -> fetch -> aggregate -> classify -> history -> narrate -> render -> validate.

Modes: ``report`` / ``triage`` (half-month, MoM) and ``legacy14`` (14 days ending
yesterday vs the 14 days before; legacy routine parity, used for the parallel
run only). A failing quality gate routes the run to internal review; there is
no way to force a send (L12, D-2).

``run`` is pure with respect to its inputs: no network, no clock, no randomness.
Rendering and dispatch are WP2+/WP3 and are not invoked here.
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Iterable, Sequence
from datetime import date

from . import analytics, coverage, render
from .classify import classify, derive_status, sort_findings
from .config import Config
from .domain import FindingEvent, FindingType, Mode, Period, PeriodSet, RunResult
from .history import HistoryEntry, apply_history, gap_note
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
    history: Sequence[HistoryEntry] = (),
) -> RunResult:
    """Execute one deterministic run.

    ``periods`` overrides the calendar-derived periods (backfills/replays).
    ``history`` holds earlier runs, oldest first (e.g. the imported legacy JSON),
    for the continuity rules and the gap check.
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
    findings, history_notes = apply_history(classify(cur, prior, config), views["project_service"], history, config)
    findings = sort_findings(findings)
    status = derive_status(findings, config)
    top = analytics.top_projects(views["project"], config.top_n_projects)
    drill_keys = [
        (f.project_id, f.service_name)
        for f in findings
        if f.level == "service" and (f.rule == "new_cost_source" or f.type is FindingType.PENURUNAN_BESAR)
    ]
    methodology = [
        n
        for n in (
            gap_note(history, ps.current),
            analytics.project_rename_note(cur),
            analytics.null_project_hint_note(cur, prior, config.null_project_hint_services),
        )
        if n
    ]

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
        top_projects=top,
        unmapped_projects=unmapped,
        notes=tuple(notes),
        project_overview=analytics.project_overview(views["project"], config.overview_rows),
        service_breakdown=analytics.service_breakdown(cur, prior, top),
        sku_drilldowns={k: analytics.sku_drilldown(cur, prior, *k) for k in drill_keys},
        methodology_notes=tuple(methodology),
        history_notes=history_notes,
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
    result = dataclasses.replace(result, narrative=text, subject=render.build_subject(result))
    result = dataclasses.replace(result, plain_text=render.build_plain_text(result, config))

    # A failing quality gate routes to internal review, never to recipients (D-2).
    report = validate_run(result, config, events=finding_events)
    return dataclasses.replace(result, validation=report, route="dispatch" if report.ok else "review")


def is_dispatchable(result: RunResult) -> bool:
    """True only for a run that passed the quality gate (L12). There is no override."""
    return result.validation.ok and result.route == "dispatch"
