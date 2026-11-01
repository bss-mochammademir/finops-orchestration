"""Configuration loading (TOML via stdlib ``tomllib``).

The config holds thresholds, status colours and routing *keys* only. It must
never contain credentials or endpoint URLs: those live in Secret Manager and are
resolved by the dispatcher at runtime (WP2). ``load_config`` rejects keys that
look like they carry credentials.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from .domain import Status

# Key fragments that indicate a credential or endpoint was put in config.
_FORBIDDEN_KEY_FRAGMENTS = (
    "secret",
    "token",
    "credential",
    "passwd",
    "api_key",
    "apikey",
    "private_key",
    "webhook_url",
    "url",
)


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Thresholds:
    spike_pct_min: Decimal = Decimal("25")
    spike_delta_min_idr: Decimal = Decimal("250000")
    new_cost_min_idr: Decimal = Decimal("100000")
    drop_pct_min: Decimal = Decimal("25")
    drop_delta_min_idr: Decimal = Decimal("500000")
    large_spike_pct: Decimal = Decimal("100")
    large_spike_delta_idr: Decimal = Decimal("1000000")
    anomaly_min_findings: int = 3
    # L2: "new cost source" when the prior amount is ~0 (<= this value).
    new_cost_prior_max_idr: Decimal = Decimal("1000")
    # L2: large absolute rise relative to the project's typical (prior-period) cost.
    abs_rise_project_share_pct: Decimal = Decimal("10")
    # L8: watchlist outside the top projects.
    watch_swing_pct: Decimal = Decimal("50")
    watch_swing_min_idr: Decimal = Decimal("100000")
    watch_new_cost_min_idr: Decimal = Decimal("10000")
    storage_growth_pct: Decimal = Decimal("20")
    storage_growth_min_idr: Decimal = Decimal("50000")
    compute_flat_pct: Decimal = Decimal("5")
    # L4: |pct| at or below this counts as "flat" for continuity notes.
    stable_pct_max: Decimal = Decimal("10")


def _parse_fraction(v: Any) -> Decimal:
    """``"1/2"`` -> ``Decimal('0.5')``; plain numbers are accepted too."""
    text = str(v).strip()
    if "/" in text:
        num, den = text.split("/", 1)
        return Decimal(num.strip()) / Decimal(den.strip())
    return Decimal(text)


@dataclass(frozen=True)
class Config:
    version: str = "0"
    thresholds: Thresholds = field(default_factory=Thresholds)
    cyclical_services: tuple[str, ...] = ("Cloud Monitoring", "Cloud Build")
    periodic_services: tuple[str, ...] = ("Cloud Domains", "Certificate Manager", "Support")
    """L3: services billed periodically/annually (domain, TLS certificate, annual support)."""
    periodic_fractions: tuple[Decimal, ...] = tuple(
        _parse_fraction(f) for f in ("1/2", "1/3", "1/4", "2/3", "3/4")
    )
    """L3: cur/prior ratios that indicate a pro-rated periodic charge."""
    periodic_fraction_tolerance_idr: Decimal = Decimal("1")
    storage_services: tuple[str, ...] = ("Cloud Storage",)
    compute_services: tuple[str, ...] = (
        "Compute Engine",
        "Cloud Run",
        "Cloud Run Functions",
        "Cloud Functions",
        "Kubernetes Engine",
        "App Engine",
    )
    null_project_hint_services: tuple[str, ...] = ("Vertex AI Search",)
    """L10: services that, on a null-project row, hint at Gemini Enterprise."""
    recurring_min_runs: int = 3
    """L4: consecutive runs (incl. the current one) after which a rise stays flagged."""
    history_max_entries: int = 6
    status_colors: dict[str, str] = field(
        default_factory=lambda: {
            Status.NORMAL.name: "#2e7d32",
            Status.PERLU_PERHATIAN.name: "#f9a825",
            Status.ANOMALI.name: "#c62828",
        }
    )
    normal_border: str = "#f9a825"
    lower_confidence_border: str = "#9aa5b1"
    reconciliation_tolerance_idr: Decimal = Decimal("40")
    shorthand_tolerance_units: Decimal = Decimal("1")
    lag_ratio: Decimal = Decimal("0.7")
    pct_decimals: int = 2
    top_n_projects: int = 3
    overview_rows: int = 12
    """L6: project overview rows before the rest is folded into "Lainnya (N project)"."""
    review_space_key: str = "finops-review"
    team_space_keys: dict[str, str] = field(default_factory=dict)
    fingerprint: str = "default"

    @property
    def config_version(self) -> str:
        """Declared version plus content fingerprint; part of the run_id."""
        return f"{self.version}+{self.fingerprint}"

    def status_color(self, status: Status) -> str:
        return self.status_colors[status.name]


def _check_no_credentials(data: Any, path: str = "") -> None:
    if isinstance(data, dict):
        for k, v in data.items():
            lk = str(k).lower()
            if any(frag in lk for frag in _FORBIDDEN_KEY_FRAGMENTS):
                raise ConfigError(
                    f"config key '{path}{k}' looks like a credential/endpoint; "
                    "store it in Secret Manager, not in config"
                )
            _check_no_credentials(v, f"{path}{k}.")
    elif isinstance(data, list):
        for item in data:
            _check_no_credentials(item, path)
    elif isinstance(data, str) and "://" in data:
        raise ConfigError(f"config value at '{path.rstrip('.')}' contains a URL; not allowed")


def _fingerprint(data: dict[str, Any]) -> str:
    canonical = json.dumps(data, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _dec(v: Any) -> Decimal:
    return Decimal(str(v))


def config_from_dict(data: dict[str, Any]) -> Config:
    _check_no_credentials(data)
    t = data.get("thresholds", {})
    d = Thresholds()
    thresholds = Thresholds(
        spike_pct_min=_dec(t.get("spike_pct_min", d.spike_pct_min)),
        spike_delta_min_idr=_dec(t.get("spike_delta_min_idr", d.spike_delta_min_idr)),
        new_cost_min_idr=_dec(t.get("new_cost_min_idr", d.new_cost_min_idr)),
        drop_pct_min=_dec(t.get("drop_pct_min", d.drop_pct_min)),
        drop_delta_min_idr=_dec(t.get("drop_delta_min_idr", d.drop_delta_min_idr)),
        large_spike_pct=_dec(t.get("large_spike_pct", d.large_spike_pct)),
        large_spike_delta_idr=_dec(t.get("large_spike_delta_idr", d.large_spike_delta_idr)),
        anomaly_min_findings=int(t.get("anomaly_min_findings", d.anomaly_min_findings)),
        new_cost_prior_max_idr=_dec(t.get("new_cost_prior_max_idr", d.new_cost_prior_max_idr)),
        abs_rise_project_share_pct=_dec(t.get("abs_rise_project_share_pct", d.abs_rise_project_share_pct)),
        watch_swing_pct=_dec(t.get("watch_swing_pct", d.watch_swing_pct)),
        watch_swing_min_idr=_dec(t.get("watch_swing_min_idr", d.watch_swing_min_idr)),
        watch_new_cost_min_idr=_dec(t.get("watch_new_cost_min_idr", d.watch_new_cost_min_idr)),
        storage_growth_pct=_dec(t.get("storage_growth_pct", d.storage_growth_pct)),
        storage_growth_min_idr=_dec(t.get("storage_growth_min_idr", d.storage_growth_min_idr)),
        compute_flat_pct=_dec(t.get("compute_flat_pct", d.compute_flat_pct)),
        stable_pct_max=_dec(t.get("stable_pct_max", d.stable_pct_max)),
    )
    base = Config()
    status = data.get("status", {})
    colors = dict(base.status_colors)
    for name in ("NORMAL", "PERLU_PERHATIAN", "ANOMALI"):
        if name.lower() in status.get("colors", {}):
            colors[name] = status["colors"][name.lower()]
    rec = data.get("reconciliation", {})
    val = data.get("validator", {})
    rep = data.get("report", {})
    routing = data.get("routing", {})
    cls = data.get("classify", {})
    hist = data.get("history", {})
    meth = data.get("methodology", {})
    return Config(
        version=str(data.get("version", base.version)),
        thresholds=thresholds,
        cyclical_services=tuple(cls.get("cyclical_services", base.cyclical_services)),
        periodic_services=tuple(cls.get("periodic_services", base.periodic_services)),
        periodic_fractions=(
            tuple(_parse_fraction(f) for f in cls["periodic_fractions"])
            if "periodic_fractions" in cls
            else base.periodic_fractions
        ),
        periodic_fraction_tolerance_idr=_dec(
            cls.get("periodic_fraction_tolerance_idr", base.periodic_fraction_tolerance_idr)
        ),
        storage_services=tuple(cls.get("storage_services", base.storage_services)),
        compute_services=tuple(cls.get("compute_services", base.compute_services)),
        null_project_hint_services=tuple(meth.get("null_project_hint_services", base.null_project_hint_services)),
        recurring_min_runs=int(hist.get("recurring_min_runs", base.recurring_min_runs)),
        history_max_entries=int(hist.get("max_entries", base.history_max_entries)),
        status_colors=colors,
        normal_border=status.get("normal_border", base.normal_border),
        lower_confidence_border=status.get("lower_confidence_border", base.lower_confidence_border),
        reconciliation_tolerance_idr=_dec(rec.get("tolerance_idr", base.reconciliation_tolerance_idr)),
        shorthand_tolerance_units=_dec(val.get("shorthand_tolerance_units", base.shorthand_tolerance_units)),
        lag_ratio=_dec(val.get("lag_ratio", base.lag_ratio)),
        pct_decimals=int(rep.get("pct_decimals", base.pct_decimals)),
        top_n_projects=int(rep.get("top_n_projects", base.top_n_projects)),
        overview_rows=int(rep.get("overview_rows", base.overview_rows)),
        review_space_key=routing.get("review_space_key", base.review_space_key),
        team_space_keys=dict(routing.get("team_space_keys", {})),
        fingerprint=_fingerprint(data),
    )


def load_config(path: str | Path) -> Config:
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    return config_from_dict(data)


def default_config() -> Config:
    return config_from_dict({})
