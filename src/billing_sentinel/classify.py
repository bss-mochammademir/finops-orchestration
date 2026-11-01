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

The anomaly status is deliberately separate from any invoice-approval
recommendation (doc 11 F-6): nothing in this package produces approval wording.
"""

from __future__ import annotations

from decimal import Decimal

from .analytics import Aggregate, compare, project_category_code
from .config import Config
from .domain import ZERO, Confidence, Finding, FindingType, Status

_TYPE_ORDER = {
    FindingType.TEMUAN_NAIK: 0,
    FindingType.PENURUNAN_BESAR: 1,
    FindingType.WATCHLIST_NEW_COST: 2,
    FindingType.WATCHLIST: 3,
}

PROJECT_LEVEL_SERVICE = "*"
"""``service_name`` used for project-level findings (e.g. a brand-new project)."""


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


def classify(cur: Aggregate, prior: Aggregate, cfg: Config) -> tuple[Finding, ...]:
    t = cfg.thresholds
    findings: list[Finding] = []

    new_projects: set[str] = set()
    for ln in compare(cur, prior, "project"):
        (project,) = ln.key
        if ln.prior == 0 and ln.cur > 0:
            new_projects.add(project)
            if ln.cur >= t.new_cost_min_idr:
                findings.append(
                    Finding(
                        project_id=project,
                        service_name=PROJECT_LEVEL_SERVICE,
                        type=FindingType.WATCHLIST_NEW_COST,
                        confidence=Confidence.NORMAL,
                        cur=ln.cur,
                        prior=ln.prior,
                        app_category_code=project_category_code(cur, project),
                        rule="new_project",
                        level="project",
                    )
                )

    for ln in compare(cur, prior, "project_service"):
        project, service = ln.key
        if project in new_projects:
            continue
        confidence = Confidence.LOWER if service in cfg.cyclical_services else Confidence.NORMAL
        pct = ln.pct_change
        ftype: FindingType | None = None
        rule = ""
        if ln.prior == 0 and ln.cur >= t.new_cost_min_idr:
            ftype, rule = FindingType.TEMUAN_NAIK, "new_cost_source"
        elif pct is not None and pct >= t.spike_pct_min and ln.delta >= t.spike_delta_min_idr:
            ftype, rule = FindingType.TEMUAN_NAIK, "spike"
        elif pct is not None and pct <= -t.drop_pct_min and -ln.delta >= t.drop_delta_min_idr:
            ftype, rule = FindingType.PENURUNAN_BESAR, "drop"
        if ftype is None:
            continue
        rising = ftype is FindingType.TEMUAN_NAIK
        findings.append(
            Finding(
                project_id=project,
                service_name=service,
                type=ftype,
                confidence=confidence,
                cur=ln.cur,
                prior=ln.prior,
                app_category_code=project_category_code(cur, project),
                driver_sku=_driver_sku(cur, prior, project, service, rising),
                rule=rule,
            )
        )

    findings.sort(key=lambda f: (_TYPE_ORDER[f.type], -abs(f.delta), f.project_id, f.service_name))
    return tuple(findings)


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
