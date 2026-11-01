"""Findings history: legacy JSON import (L5) and cross-run continuity (L4).

Legacy format (``gcp_billing_findings_history.json``, HANDOFF §12)::

    {"schema_version": 1,
     "history": [  # at most 6 entries, newest LAST
       {"period_start": "YYYY-MM-DD", "period_end": "YYYY-MM-DD",
        "generated_at": "...", "status": "...",
        "total_current": n, "total_prior": n, "pct_change": n,
        "items": [{"project": ..., "service": ..., "type": ...,
                   "pct_change": n|null, "cur": n, "prior": n, "note": "..."?}]}]}

``type`` is one of ``temuan_naik``, ``penurunan_besar``, ``watchlist``,
``watchlist_new_cost``. Entries are converted to rows shaped like the
``findings`` table (``sql/ddl.sql``) for the T1 migration.

Continuity rules (L4), applied after classification and before the status:
- a ``temuan_naik`` that appears in >= ``recurring_min_runs`` consecutive runs
  (the current run included) stays flagged even below ``spike_pct_min``, as long
  as the cost still rises. A sub-threshold recurring item is lower-confidence
  (it is flagged, but never escalates the status on its own);
- an item from the previous run that does not reappear and whose cost is flat
  (|pct| <= ``stable_pct_max``) or falling gets an "improved/stable" note;
- a ``penurunan_besar`` from the previous run whose cost stays low is not
  flagged again; it only gets an "already known" note.

Nothing here performs I/O beyond reading a local JSON file the caller names.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from .config import Config
from .domain import (
    PROJECT_SERVICE_SEP,
    Confidence,
    Finding,
    FindingType,
    Line,
    Mode,
    Period,
    make_finding_key,
)
from .money import format_idr, format_pct
from .narrative import format_date_id as _fmt_date

SUPPORTED_SCHEMA_VERSION = 1
LEGACY_MAX_ENTRIES = 6


class HistoryError(ValueError):
    """The history document does not match the legacy schema v1."""


@dataclass(frozen=True)
class HistoryItem:
    project: str
    service: str
    type: FindingType
    cur: Decimal
    prior: Decimal
    pct_change: Decimal | None = None
    note: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.project, self.service)


@dataclass(frozen=True)
class HistoryEntry:
    period_start: date
    period_end: date
    generated_at: str
    status: str
    total_current: Decimal
    total_prior: Decimal
    pct_change: Decimal | None
    items: tuple[HistoryItem, ...] = ()

    def keys_of(self, ftype: FindingType) -> set[tuple[str, str]]:
        return {i.key for i in self.items if i.type is ftype}

    def item(self, key: tuple[str, str], ftype: FindingType) -> HistoryItem | None:
        return next((i for i in self.items if i.key == key and i.type is ftype), None)


# --------------------------------------------------------------------------- parsing
def _dec(v: Any, where: str) -> Decimal:
    if isinstance(v, bool) or v is None:
        raise HistoryError(f"{where}: expected a number, got {v!r}")
    try:
        return Decimal(str(v))
    except Exception as exc:  # noqa: BLE001
        raise HistoryError(f"{where}: expected a number, got {v!r}") from exc


def _opt_dec(v: Any, where: str) -> Decimal | None:
    return None if v is None else _dec(v, where)


def _date(v: Any, where: str) -> date:
    try:
        return date.fromisoformat(str(v))
    except ValueError as exc:
        raise HistoryError(f"{where}: expected YYYY-MM-DD, got {v!r}") from exc


def _str(v: Any, where: str) -> str:
    if not isinstance(v, str) or not v.strip():
        raise HistoryError(f"{where}: expected a non-empty string")
    return v.strip()


def parse_legacy_history(data: Any, max_entries: int = LEGACY_MAX_ENTRIES) -> tuple[HistoryEntry, ...]:
    """Validate and parse a legacy schema v1 document (newest entry last)."""
    if not isinstance(data, dict):
        raise HistoryError("history document must be a JSON object")
    if data.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise HistoryError(f"unsupported schema_version {data.get('schema_version')!r}; expected 1")
    raw = data.get("history")
    if not isinstance(raw, list):
        raise HistoryError("'history' must be a list")
    if len(raw) > max_entries:
        raise HistoryError(f"'history' has {len(raw)} entries; legacy schema keeps at most {max_entries}")
    entries: list[HistoryEntry] = []
    for i, e in enumerate(raw):
        w = f"history[{i}]"
        if not isinstance(e, dict):
            raise HistoryError(f"{w}: must be an object")
        items: list[HistoryItem] = []
        for j, it in enumerate(e.get("items") or []):
            wi = f"{w}.items[{j}]"
            if not isinstance(it, dict):
                raise HistoryError(f"{wi}: must be an object")
            try:
                ftype = FindingType(it.get("type"))
            except ValueError as exc:
                raise HistoryError(f"{wi}: unknown type {it.get('type')!r}") from exc
            items.append(
                HistoryItem(
                    project=_str(it.get("project"), f"{wi}.project"),
                    service=_str(it.get("service"), f"{wi}.service"),
                    type=ftype,
                    cur=_dec(it.get("cur"), f"{wi}.cur"),
                    prior=_dec(it.get("prior"), f"{wi}.prior"),
                    pct_change=_opt_dec(it.get("pct_change"), f"{wi}.pct_change"),
                    note=str(it.get("note") or ""),
                )
            )
        start, end = _date(e.get("period_start"), f"{w}.period_start"), _date(e.get("period_end"), f"{w}.period_end")
        if end < start:
            raise HistoryError(f"{w}: period_end before period_start")
        entries.append(
            HistoryEntry(
                period_start=start,
                period_end=end,
                generated_at=str(e.get("generated_at") or ""),
                status=str(e.get("status") or ""),
                total_current=_dec(e.get("total_current"), f"{w}.total_current"),
                total_prior=_dec(e.get("total_prior"), f"{w}.total_prior"),
                pct_change=_opt_dec(e.get("pct_change"), f"{w}.pct_change"),
                items=tuple(items),
            )
        )
    for a, b in zip(entries, entries[1:]):
        if b.period_end < a.period_end:
            raise HistoryError("history entries must be ordered oldest first (newest last)")
    return tuple(entries)


def load_legacy_history(path: str | Path, max_entries: int = LEGACY_MAX_ENTRIES) -> tuple[HistoryEntry, ...]:
    with open(path, encoding="utf-8") as fh:
        return parse_legacy_history(json.load(fh), max_entries)


# --------------------------------------------------------------------------- migration
def legacy_run_id(entry: HistoryEntry) -> str:
    """Deterministic run id for an imported legacy run (mode ``legacy14``)."""
    raw = f"legacy-import|{entry.period_start.isoformat()}|{entry.period_end.isoformat()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def to_findings_rows(entries: Iterable[HistoryEntry]) -> list[dict[str, Any]]:
    """Rows shaped like the ``findings`` table (``sql/ddl.sql``).

    Legacy items carry no confidence, app category or driver SKU; those columns
    are ``None`` rather than guessed. ``run_ts`` keeps the legacy
    ``generated_at`` text verbatim (parsing into TIMESTAMP is done at load time).
    """
    rows: list[dict[str, Any]] = []
    for e in entries:
        run_id = legacy_run_id(e)
        for it in e.items:
            rows.append(
                {
                    "run_id": run_id,
                    "run_ts": e.generated_at,
                    "mode": Mode.LEGACY14.value,
                    "period_start": e.period_start,
                    "period_end": e.period_end,
                    "level": "service",
                    "app_category_code": None,
                    "project_id": it.project,
                    "service": it.service,
                    "finding_key": make_finding_key(it.project, it.service, it.type),
                    "type": it.type.value,
                    "confidence": None,
                    "cur": it.cur,
                    "prior": it.prior,
                    "pct_change": it.pct_change,
                    "driver_sku": None,
                    "recurring_count": None,
                    "note": it.note or None,
                }
            )
    return rows


# --------------------------------------------------------------------------- gap (L5)
def gap_note(entries: Sequence[HistoryEntry], current: Period) -> str | None:
    """Methodology note when the last run does not end the day before this run starts."""
    if not entries:
        return None
    last_end = entries[-1].period_end
    expected = current.start - timedelta(days=1)
    if last_end == expected:
        return None
    if last_end < expected:
        missing = Period(last_end + timedelta(days=1), expected)
        span = _fmt_date(missing.start) if missing.days == 1 else f"{_fmt_date(missing.start)} s.d. {_fmt_date(missing.end)}"
        return (
            f"Catatan histori: run sebelumnya mencakup s.d. {_fmt_date(last_end)} sedangkan periode ini mulai "
            f"{_fmt_date(current.start)}, sehingga {span} ({missing.days} hari) tidak tercakup sebagai periode "
            "berjalan di run mana pun (hanya sebagai pembanding)."
        )
    return (
        f"Catatan histori: run sebelumnya mencakup s.d. {_fmt_date(last_end)}, tumpang tindih dengan periode ini "
        f"yang mulai {_fmt_date(current.start)}; kontinuitas temuan perlu dibaca dengan hati-hati."
    )


# --------------------------------------------------------------------------- continuity (L4)
def consecutive_runs(entries: Sequence[HistoryEntry], key: tuple[str, str], ftype: FindingType) -> int:
    """Number of most recent consecutive entries that contain ``key`` with ``ftype``."""
    n = 0
    for e in reversed(entries):
        if key not in e.keys_of(ftype):
            break
        n += 1
    return n


def _label(key: tuple[str, str]) -> str:
    return f"{key[0]}{PROJECT_SERVICE_SEP}{key[1]}"


def apply_history(
    findings: Sequence[Finding],
    project_service_lines: Iterable[Line],
    entries: Sequence[HistoryEntry],
    cfg: Config,
) -> tuple[tuple[Finding, ...], tuple[str, ...]]:
    """Apply L4 continuity rules. Returns (findings, history notes)."""
    if not entries:
        return tuple(findings), ()
    lines = {ln.key: ln for ln in project_service_lines}
    last = entries[-1]
    t = cfg.thresholds
    min_prev = max(cfg.recurring_min_runs - 1, 1)
    out: list[Finding] = []
    notes: list[str] = []
    current_keys = {(f.project_id, f.service_name) for f in findings}

    # Recurring temuan_naik and already-known drops among the current findings.
    for f in findings:
        key = (f.project_id, f.service_name)
        if f.type is FindingType.TEMUAN_NAIK:
            prev = consecutive_runs(entries, key, FindingType.TEMUAN_NAIK)
            if prev:
                f = dataclasses.replace(f, recurring_count=prev + 1)
        elif f.type is FindingType.PENURUNAN_BESAR:
            old = last.item(key, FindingType.PENURUNAN_BESAR)
            if old is not None and f.cur <= old.cur * (1 + t.stable_pct_max / 100):
                notes.append(
                    f"{_label(key)}: penurunan besar sudah diketahui sejak run sebelumnya dan biaya tetap rendah "
                    f"({format_idr(f.cur)}); tidak di-flag ulang."
                )
                continue
        out.append(f)

    # Sub-threshold recurring rises that classify did not flag this run.
    candidates = {k for e in entries for k in e.keys_of(FindingType.TEMUAN_NAIK)}
    for key in sorted(candidates - current_keys):
        prev = consecutive_runs(entries, key, FindingType.TEMUAN_NAIK)
        ln = lines.get(key)
        if prev >= min_prev and ln is not None and ln.delta > 0:
            out.append(
                Finding(
                    project_id=key[0],
                    service_name=key[1],
                    type=FindingType.TEMUAN_NAIK,
                    confidence=Confidence.LOWER,
                    cur=ln.cur,
                    prior=ln.prior,
                    rule="recurring",
                    recurring_count=prev + 1,
                    note=f"recurring: naik {prev + 1} run berturut-turut (di bawah ambang lonjakan)",
                )
            )

    flagged_now = {(f.project_id, f.service_name) for f in out}
    for it in last.items:
        if it.key in flagged_now or it.key in current_keys:
            continue
        ln = lines.get(it.key)
        if ln is None:
            continue
        if it.type is FindingType.PENURUNAN_BESAR:
            if ln.cur <= it.cur * (1 + t.stable_pct_max / 100):
                notes.append(
                    f"{_label(it.key)}: penurunan besar sudah diketahui sejak run sebelumnya; biaya tetap rendah "
                    f"({format_idr(ln.cur)})."
                )
            continue
        pct = ln.pct_change
        if pct is not None and pct <= t.stable_pct_max:
            state = "stabil" if abs(pct) <= t.stable_pct_max else "membaik"
            notes.append(
                f"{_label(it.key)}: temuan run sebelumnya tidak muncul lagi; biaya {state} "
                f"({format_idr(ln.prior)} → {format_idr(ln.cur)}, {format_pct(pct, cfg.pct_decimals)})."
            )
    return tuple(out), tuple(dict.fromkeys(notes))
