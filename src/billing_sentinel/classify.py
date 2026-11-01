"""Finding classification and run status (prototype rules, thresholds from config).

Status rules (lessons §8.7, prototype ``build.py``):
- no counted findings                                   -> ``Normal`` (#2e7d32)
- >= ``anomaly_min_findings`` (3) normal-confidence findings,
  or any normal-confidence *large spike*
  (pct > ``large_spike_pct`` (100) and delta > ``large_spike_delta_idr`` (Rp1.000.000))
                                                         -> ``Ada Indikasi Anomali`` (#c62828)
- otherwise                                              -> ``Perlu Perhatian`` (#f9a825)

Counted findings are ``temuan_naik`` only (section 3 "Temuan yang Ditandai" of
the prototype). ``penurunan_besar`` and watchlist items are context and never
change the status. Lower-confidence findings (grey border #9aa5b1) make a run
non-Normal but are excluded from the ">= 3" count and cannot be a large spike.

Finding rules (legacy routine parity, WP1b):
- L2 ``temuan_naik``: pct >= ``spike_pct_min`` with delta >= ``spike_delta_min_idr``
  (``spike``); a *new cost source* whose prior amount is ~0
  (<= ``new_cost_prior_max_idr``) (``new_cost_source``); or a large absolute rise
  relative to the project's typical cost, i.e. delta >= ``abs_rise_project_share_pct``
  of the project's prior total and >= ``spike_delta_min_idr`` (``abs_rise_vs_project``).
- L3 periodic/annual services (config ``periodic_services``) and drops to an
  exact fraction of the prior amount (``periodic_fractions``, e.g. half) are
  lower-confidence: grey border, never escalate the status on their own.
- L8 watchlist outside the top projects: large project swing (named with its
  driving service), small new cost category, and storage growing while compute
  stays flat (possible missing lifecycle policy).
- L13 every finding names a concrete "Project — Service"; a brand-new project
  is named with its largest service.

The anomaly status is deliberately separate from any invoice-approval
recommendation (doc 11 F-6): nothing in this package produces approval wording.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from .analytics import Aggregate, compare, project_category_code, top_projects
from .config import Config
from .domain import ZERO, Confidence, Finding, FindingType, Line, Status

_TYPE_ORDER = {
    FindingType.TEMUAN_NAIK: 0,
    FindingType.PENURUNAN_BESAR: 1,
    FindingType.WATCHLIST_NEW_COST: 2,
    FindingType.WATCHLIST: 3,
}

PERIODIC_NOTE = "biaya periodik/tahunan (lower-confidence)"
FRACTION_NOTE = "turun tepat menjadi pecahan {frac} dari periode sebelumnya; kemungkinan biaya periodik (lower-confidence)"
LIFECYCLE_NOTE = "storage tumbuh tanpa compute tumbuh; indikasi lifecycle policy hilang"


def _driver_sku(cur: Aggregate, prior: Aggregate, project: str, service: str, rising: bool) -> str | None:
    skus = {
        k[2]
        for agg in (cur, prior)
        for k in agg.views["project_service_sku"]
        if k[0] == project and k[1] == service and k[2]
    }
    if not skus:
        return None

    def delta(sku: str) -> Decimal:
        key = (project, service, sku)
        return cur.views["project_service_sku"].get(key, ZERO) - prior.views["project_service_sku"].get(key, ZERO)

    ranked = sorted(skus, key=lambda s: (-delta(s) if rising else delta(s), s))
    return ranked[0]


def is_large_spike(finding: Finding, cfg: Config) -> bool:
    """Normal-confidence ``temuan_naik`` with pct > 100% and delta > Rp1.000.000 (config)."""
    if finding.type is not FindingType.TEMUAN_NAIK or finding.confidence is not Confidence.NORMAL:
        return False
    pct = finding.pct_change
    t = cfg.thresholds
    return pct is not None and pct > t.large_spike_pct and finding.delta > t.large_spike_delta_idr


def exact_fraction(cur: Decimal, prior: Decimal, cfg: Config) -> Decimal | None:
    """The configured fraction ``f`` with ``|cur - prior x f| <= tolerance``, if any (L3)."""
    if prior <= 0 or cur <= 0 or cur >= prior:
        return None
    for frac in cfg.periodic_fractions:
        if abs(cur - prior * frac) <= cfg.periodic_fraction_tolerance_idr:
            return frac
    return None


def _fraction_text(frac: Decimal) -> str:
    known = {Decimal(1) / 2: "1/2", Decimal(1) / 3: "1/3", Decimal(1) / 4: "1/4",
             Decimal(2) / 3: "2/3", Decimal(3) / 4: "3/4"}
    return known.get(frac, str(frac))


def _largest_service(cur: Aggregate, prior: Aggregate, project: str, by_delta: bool) -> str:
    lines = [ln for ln in compare(cur, prior, "project_service") if ln.key[0] == project]
    if by_delta:
        lines.sort(key=lambda ln: (-abs(ln.delta), ln.key))
    return lines[0].key[1]


def _project_lines(cur: Aggregate, prior: Aggregate) -> dict[str, Line]:
    return {ln.key[0]: ln for ln in compare(cur, prior, "project")}


def _pct(cur: Decimal, prior: Decimal) -> Decimal | None:
    return None if prior == 0 else (cur - prior) / abs(prior) * 100


def classify(cur: Aggregate, prior: Aggregate, cfg: Config) -> tuple[Finding, ...]:
    t = cfg.thresholds
    findings: list[Finding] = []
    projects = _project_lines(cur, prior)
    top = set(top_projects(projects.values(), cfg.top_n_projects))

    new_projects: set[str] = set()
    for project, ln in projects.items():
        if ln.prior == 0 and ln.cur > 0:
            new_projects.add(project)
            if ln.cur >= t.new_cost_min_idr:
                findings.append(
                    Finding(
                        project_id=project,
                        service_name=_largest_service(cur, prior, project, by_delta=False),
                        type=FindingType.WATCHLIST_NEW_COST,
                        confidence=Confidence.NORMAL,
                        cur=ln.cur,
                        prior=ln.prior,
                        app_category_code=project_category_code(cur, project),
                        rule="new_project",
                        level="project",
                        note="project baru (tanpa biaya di periode pembanding)",
                    )
                )

    flagged: set[tuple[str, str]] = set()
    small_new: list[Line] = []
    for ln in compare(cur, prior, "project_service"):
        project, service = ln.key
        if project in new_projects:
            continue
        periodic = service in cfg.periodic_services
        lower = periodic or service in cfg.cyclical_services
        note = PERIODIC_NOTE if periodic else ""
        pct = ln.pct_change
        project_prior = projects[project].prior
        ftype: FindingType | None = None
        rule = ""
        is_new = ln.prior <= t.new_cost_prior_max_idr and ln.cur > ln.prior
        if is_new and ln.cur >= t.new_cost_min_idr:
            ftype, rule = FindingType.TEMUAN_NAIK, "new_cost_source"
        elif pct is not None and pct >= t.spike_pct_min and ln.delta >= t.spike_delta_min_idr:
            ftype, rule = FindingType.TEMUAN_NAIK, "spike"
        elif (
            project_prior > 0
            and ln.delta >= t.spike_delta_min_idr
            and ln.delta * 100 >= project_prior * t.abs_rise_project_share_pct
        ):
            ftype, rule = FindingType.TEMUAN_NAIK, "abs_rise_vs_project"
        elif pct is not None and pct <= -t.drop_pct_min and -ln.delta >= t.drop_delta_min_idr:
            ftype, rule = FindingType.PENURUNAN_BESAR, "drop"
            frac = exact_fraction(ln.cur, ln.prior, cfg)
            if frac is not None:
                lower = True
                note = FRACTION_NOTE.format(frac=_fraction_text(frac))
        if ftype is None:
            if is_new and ln.cur >= t.watch_new_cost_min_idr:
                small_new.append(ln)
            continue
        rising = ftype is FindingType.TEMUAN_NAIK
        flagged.add((project, service))
        findings.append(
            Finding(
                project_id=project,
                service_name=service,
                type=ftype,
                confidence=Confidence.LOWER if lower else Confidence.NORMAL,
                cur=ln.cur,
                prior=ln.prior,
                app_category_code=project_category_code(cur, project),
                driver_sku=_driver_sku(cur, prior, project, service, rising),
                rule=rule,
                note=note,
            )
        )

    findings += _watchlist(cur, prior, cfg, projects, top | new_projects, flagged, small_new)
    return sort_findings(findings)


def sort_findings(findings: Iterable[Finding]) -> tuple[Finding, ...]:
    """Deterministic order: type, largest absolute change, project, service."""
    return tuple(sorted(findings, key=lambda f: (_TYPE_ORDER[f.type], -abs(f.delta), f.project_id, f.service_name)))


def _watchlist(
    cur: Aggregate,
    prior: Aggregate,
    cfg: Config,
    projects: dict[str, Line],
    excluded: set[str],
    flagged: set[tuple[str, str]],
    small_new: list[Line],
) -> list[Finding]:
    """L8: context items for projects outside the top projects (never counted)."""
    t = cfg.thresholds
    out: list[Finding] = []
    flagged_projects = {p for p, _ in flagged}

    def add(project: str, service: str, ftype: FindingType, c: Decimal, p: Decimal, rule: str, note: str = "") -> None:
        flagged.add((project, service))
        out.append(
            Finding(
                project_id=project,
                service_name=service,
                type=ftype,
                confidence=Confidence.NORMAL,
                cur=c,
                prior=p,
                app_category_code=project_category_code(cur, project),
                driver_sku=_driver_sku(cur, prior, project, service, c >= p),
                rule=rule,
                note=note,
                level="project" if rule == "swing" else "service",
            )
        )

    for project, ln in sorted(projects.items()):
        if project in excluded:
            continue
        pct = ln.pct_change
        # Large swing: the project is named with its driving service.
        if (
            project not in flagged_projects
            and pct is not None
            and abs(pct) >= t.watch_swing_pct
            and abs(ln.delta) >= t.watch_swing_min_idr
        ):
            service = _largest_service(cur, prior, project, by_delta=True)
            add(project, service, FindingType.WATCHLIST, ln.cur, ln.prior, "swing",
                f"total project berubah {'naik' if ln.delta > 0 else 'turun'} besar")
        # Storage grows while compute does not.
        svc = {k[1]: (cur.views["project_service"].get(k, ZERO), prior.views["project_service"].get(k, ZERO))
               for agg in (cur, prior) for k in agg.views["project_service"] if k[0] == project}
        st_c = sum((v[0] for s, v in svc.items() if s in cfg.storage_services), ZERO)
        st_p = sum((v[1] for s, v in svc.items() if s in cfg.storage_services), ZERO)
        cp_c = sum((v[0] for s, v in svc.items() if s in cfg.compute_services), ZERO)
        cp_p = sum((v[1] for s, v in svc.items() if s in cfg.compute_services), ZERO)
        st_pct, cp_pct = _pct(st_c, st_p), _pct(cp_c, cp_p)
        compute_flat = cp_c <= cp_p or (cp_pct is not None and cp_pct <= t.compute_flat_pct)
        if (
            st_pct is not None
            and st_pct >= t.storage_growth_pct
            and st_c - st_p >= t.storage_growth_min_idr
            and compute_flat
        ):
            storage = max((s for s in svc if s in cfg.storage_services), key=lambda s: (svc[s][0] - svc[s][1], s))
            if (project, storage) not in flagged:
                add(project, storage, FindingType.WATCHLIST, svc[storage][0], svc[storage][1],
                    "storage_without_compute", LIFECYCLE_NOTE)

    for ln in small_new:
        project, service = ln.key
        if project in excluded or (project, service) in flagged:
            continue
        add(project, service, FindingType.WATCHLIST_NEW_COST, ln.cur, ln.prior, "new_cost_small",
            "kategori biaya baru (di bawah ambang temuan)")
    return out


def counted_findings(findings: tuple[Finding, ...] | list[Finding]) -> list[Finding]:
    return [f for f in findings if f.type is FindingType.TEMUAN_NAIK]


def derive_status(findings: tuple[Finding, ...] | list[Finding], cfg: Config) -> Status:
    counted = counted_findings(findings)
    if not counted:
        return Status.NORMAL
    normal = [f for f in counted if f.confidence is Confidence.NORMAL]
    if len(normal) >= cfg.thresholds.anomaly_min_findings or any(is_large_spike(f, cfg) for f in normal):
        return Status.ANOMALI
    return Status.PERLU_PERHATIAN


def border_color(finding: Finding, cfg: Config) -> str:
    """Left-border colour of a finding card (amber normal, grey lower-confidence)."""
    return cfg.lower_confidence_border if finding.confidence is Confidence.LOWER else cfg.normal_border
