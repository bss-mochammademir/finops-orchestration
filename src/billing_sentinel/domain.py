"""Core domain types for the deterministic billing sentinel.

All monetary amounts are ``decimal.Decimal`` in the billing currency (IDR).
Nothing in this module talks to an external system.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum

UNMAPPED = "UNMAPPED"
"""App-category code used when a usage row carries no ``application_category`` label.

``UNMAPPED`` is *not* an accrual code; it is never counted as attributed
(doc 11 F-2). ``ac_046`` is attributed only when a human wrote that label.
"""

UNATTRIBUTED_PROJECT = "(unattributed)"
"""Project key used when the billing row has a null ``project.id`` (lessons §8.5)."""

ZERO = Decimal("0")


class Status(Enum):
    """Anomaly status of a run. Independent from any invoice-approval decision (F-6)."""

    NORMAL = "Normal"
    PERLU_PERHATIAN = "Perlu Perhatian"
    ANOMALI = "Ada Indikasi Anomali"


class FindingType(Enum):
    TEMUAN_NAIK = "temuan_naik"
    PENURUNAN_BESAR = "penurunan_besar"
    WATCHLIST = "watchlist"
    WATCHLIST_NEW_COST = "watchlist_new_cost"


class Confidence(Enum):
    NORMAL = "normal"
    LOWER = "lower"


class FindingState(Enum):
    """Human state of a finding, stored append-only in ``finding_events``."""

    NEW = "new"
    INVESTIGATING = "investigating"
    ACKNOWLEDGED_NORMAL = "acknowledged_normal"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class Mode(Enum):
    TRIAGE = "triage"
    REPORT = "report"
    LEGACY14 = "legacy14"
    """14 days ending yesterday vs the 14 days before (legacy routine, parallel run only)."""


PROJECT_SERVICE_SEP = " — "
"""Separator of the mandatory "Project — Service" label of every finding (L13)."""


def make_finding_key(project_id: str, service_name: str, ftype: "FindingType | str") -> str:
    """Stable key = hash(project_id, service_name, type) (doc 11 §4 (5))."""
    tval = ftype.value if isinstance(ftype, Enum) else str(ftype)
    raw = f"{project_id}|{service_name}|{tval}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class CostRow:
    """One aggregated daily cost row, mirroring ``fact_daily_cost``.

    ``app_category_code`` is the ``application_category`` project label *at the
    time of usage* (doc 11 F-1); empty/None means the row is unmapped.
    ``project_name`` is informational only and is never used for grouping.
    """

    charge_date: date
    project_id: str | None
    service_name: str
    gross_cost: Decimal
    credits: Decimal = ZERO
    sku_name: str = ""
    app_category_code: str | None = None
    project_name: str | None = None
    invoice_month: str = ""
    currency: str = "IDR"

    @property
    def net_cost(self) -> Decimal:
        """Net cost = cost + credits (credits are negative in the export)."""
        return self.gross_cost + self.credits


@dataclass(frozen=True)
class Period:
    """Inclusive date range."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"period end {self.end} before start {self.start}")

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def contains(self, d: date) -> bool:
        return self.start <= d <= self.end

    def dates(self) -> list[date]:
        return [self.start + timedelta(days=i) for i in range(self.days)]

    def __str__(self) -> str:
        return f"{self.start.isoformat()}..{self.end.isoformat()}"


@dataclass(frozen=True)
class PeriodSet:
    """Current period plus comparison periods.

    ``mom`` is the primary (cycle-aware) comparison: same half of the previous
    month. ``prior_half`` is the secondary comparison (the half immediately
    before). Either comparison may be overridden (e.g. for regression replays).
    """

    current: Period
    mom: Period
    prior_half: Period | None = None


@dataclass(frozen=True)
class Line:
    """One comparison line in a view (project, service, category, ...)."""

    key: tuple[str, ...]
    cur: Decimal
    prior: Decimal

    @property
    def delta(self) -> Decimal:
        return self.cur - self.prior

    @property
    def pct_change(self) -> Decimal | None:
        """Percent change; ``None`` when the prior amount is zero ("BARU")."""
        if self.prior == 0:
            return None
        return (self.cur - self.prior) / abs(self.prior) * 100


@dataclass(frozen=True)
class Finding:
    project_id: str
    service_name: str
    type: FindingType
    confidence: Confidence
    cur: Decimal
    prior: Decimal
    app_category_code: str = UNMAPPED
    driver_sku: str | None = None
    rule: str = ""
    level: str = "service"
    note: str = ""
    """Short deterministic explanation (e.g. periodic cost, recurring, lifecycle hint)."""
    recurring_count: int = 0
    """Consecutive runs (including this one) in which this finding appeared; 0 = unknown/new."""

    @property
    def delta(self) -> Decimal:
        return self.cur - self.prior

    @property
    def pct_change(self) -> Decimal | None:
        if self.prior == 0:
            return None
        return (self.cur - self.prior) / abs(self.prior) * 100

    @property
    def label(self) -> str:
        """Mandatory "Project — Service" label (L13)."""
        return f"{self.project_id}{PROJECT_SERVICE_SEP}{self.service_name}"

    @property
    def finding_key(self) -> str:
        return make_finding_key(self.project_id, self.service_name, self.type)


@dataclass(frozen=True)
class FindingEvent:
    """Human state change of a finding (``finding_events`` table).

    ``actor_principal`` must be a service/system identity, never a person's name.
    """

    finding_key: str
    state: FindingState
    event_date: date
    reason: str = ""
    expires_on: date | None = None
    actor_principal: str = ""


@dataclass(frozen=True)
class Violation:
    code: str
    message: str


@dataclass(frozen=True)
class ValidationReport:
    violations: tuple[Violation, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.violations

    def codes(self) -> set[str]:
        return {v.code for v in self.violations}


@dataclass(frozen=True)
class RunResult:
    run_id: str
    mode: Mode
    as_of: date
    periods: PeriodSet
    config_version: str
    total: Line
    """Grand total, current vs primary comparison (``periods.mom``)."""
    views: dict[str, tuple[Line, ...]]
    """Keys: ``project``, ``service``, ``category``, ``project_service``."""
    findings: tuple[Finding, ...]
    status: Status
    status_color: str
    coverage_adr003: Decimal | None
    """C_ADR003 as a fraction 0..1 of current-period net cost (None if total <= 0)."""
    daily_avg_cur: Decimal
    daily_avg_prior: Decimal
    secondary_total: Line | None = None
    """Grand total, current vs ``periods.prior_half`` (if any)."""
    top_projects: tuple[str, ...] = ()
    unmapped_projects: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    narrative: str = ""
    validation: ValidationReport = field(default_factory=ValidationReport)
    route: str = "review"
    """``dispatch`` when validation passed, otherwise ``review`` (internal review, D-2)."""
    project_overview: tuple[Line, ...] = ()
    """Top ``overview_rows`` projects plus one "Lainnya (N project)" line (L6)."""
    service_breakdown: dict[str, tuple[Line, ...]] = field(default_factory=dict)
    """Per-service lines for each top project (L7)."""
    sku_drilldowns: dict[tuple[str, str], tuple[Line, ...]] = field(default_factory=dict)
    """SKU lines for new cost sources and large drops, keyed by (project, service) (L7)."""
    methodology_notes: tuple[str, ...] = ()
    """History gap, project name change, null project hints (L5, L9, L10)."""
    history_notes: tuple[str, ...] = ()
    """Continuity notes from earlier runs: improved/stable, already known (L4)."""
    subject: str = ""
    plain_text: str = ""
    """Plain-text email body (L11); validated by the quality gate like the narrative."""
