"""Narrative generation behind a model-neutral interface (D-3, D-4).

``TemplateNarrativeProvider`` is deterministic and uses no language model; it is
both the WP1 implementation and the graceful-degradation fallback. A model-backed
provider (WP4) must implement the same protocol, receive aggregates only (never
owner/PIC data) and pass the validator like any other text.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .classify import counted_findings, is_large_spike
from .config import Config
from .domain import Confidence, Period, RunResult
from .money import format_idr, format_pct

_MONTHS_ID = (
    "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
)


def format_period_id(p: Period) -> str:
    """``2026-10-18..2026-10-31`` -> ``'18–31 Oktober 2026'``."""
    s, e = p.start, p.end
    if (s.year, s.month) == (e.year, e.month):
        return f"{s.day}–{e.day} {_MONTHS_ID[e.month - 1]} {e.year}"
    if s.year == e.year:
        return f"{s.day} {_MONTHS_ID[s.month - 1]}–{e.day} {_MONTHS_ID[e.month - 1]} {e.year}"
    return f"{s.day} {_MONTHS_ID[s.month - 1]} {s.year}–{e.day} {_MONTHS_ID[e.month - 1]} {e.year}"


@runtime_checkable
class NarrativeProvider(Protocol):
    def generate(self, result: RunResult, cfg: Config) -> str:
        """Return narrative text for ``result``. Must only restate computed numbers."""
        ...


class TemplateNarrativeProvider:
    """Deterministic Bahasa Indonesia summary built only from computed values."""

    def generate(self, result: RunResult, cfg: Config) -> str:
        d = cfg.pct_decimals
        tot = result.total
        pct = tot.pct_change
        if pct is None:
            change = "tanpa pembanding (biaya periode pembanding Rp0)"
        elif pct > 0:
            change = f"naik {format_pct(pct, d)}"
        elif pct < 0:
            change = f"turun {format_pct(abs(pct), d, signed=False)}"
        else:
            change = "tidak berubah"
        cur_p, cmp_p = result.periods.current, result.periods.mom
        parts = [
            f"Total net cost GCP periode {format_period_id(cur_p)} adalah {format_idr(tot.cur)}, "
            f"{change} dibanding {format_idr(tot.prior)} pada periode pembanding {format_period_id(cmp_p)}."
        ]
        if cur_p.days != cmp_p.days:
            parts.append(
                f"Karena panjang periode berbeda ({cur_p.days} vs {cmp_p.days} hari), rata-rata harian "
                f"{format_idr(result.daily_avg_cur)} vs {format_idr(result.daily_avg_prior)}."
            )
        if result.top_projects:
            by_project = {ln.key[0]: ln for ln in result.views["project"]}
            tops = ", ".join(f"{p} ({format_idr(by_project[p].cur)})" for p in result.top_projects)
            parts.append(f"Project dengan biaya tertinggi: {tops}.")

        counted = counted_findings(result.findings)
        normal = [f for f in counted if f.confidence is Confidence.NORMAL]
        lower = [f for f in counted if f.confidence is Confidence.LOWER]
        status_line = f"Status: {result.status.value}"
        if counted:
            status_line += f" — {len(normal)} temuan normal-confidence dan {len(lower)} temuan lower-confidence"
            spikes = [f for f in normal if is_large_spike(f, cfg)]
            if spikes:
                status_line += f", termasuk lonjakan besar di {spikes[0].project_id} — {spikes[0].service_name}"
        parts.append(status_line + ".")
        for f in counted:
            parts.append(
                f"Temuan {f.project_id} — {f.service_name}: {format_idr(f.prior)} → {format_idr(f.cur)} "
                f"({format_pct(f.pct_change, d)})."
            )
        if result.coverage_adr003 is not None:
            parts.append(
                f"Cakupan atribusi ADR-003 (C_ADR003): {format_pct(result.coverage_adr003 * 100, d, signed=False)}."
            )
        parts.append(
            "Status ini adalah indikasi anomali biaya, bukan rekomendasi persetujuan invoice; "
            "keputusan approval tetap berada pada IT Finance/Direksi."
        )
        return " ".join(parts)
