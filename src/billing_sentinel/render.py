"""Two-view renderer (ABB A06): inline-CSS HTML email, plain-text body, PDF archive.

Implemented in WP1b (legacy parity, L11): the email subject and the plain-text
body. Every number in the plain-text body is formatted here from computed
values and the body passes the same quality gate as the narrative.

STUB — TODO(WP3/WP4): technical view (project -> service -> SKU) for Google Chat
in WP3; executive view per ADR-003 ``ac_xxx`` (names joined from
``ref_app_category`` only, never hard-coded), inline ``style=""`` HTML
(lessons §8.8), and PDF to Cloud Storage in WP3/WP4.
"""

from __future__ import annotations

from collections.abc import Iterable

from .config import Config
from .domain import Confidence, Finding, FindingType, Line, Period, RunResult
from .money import format_idr, format_pct
from .narrative import format_date_id

SUBJECT_PREFIX = "[GCP Billing Check]"


def format_range_id(p: Period) -> str:
    """``'18 Oktober 2026 s.d. 31 Oktober 2026'``."""
    return f"{format_date_id(p.start)} s.d. {format_date_id(p.end)}"


def build_subject(result: RunResult) -> str:
    """``[GCP Billing Check] Status: {STATUS} — {start} s.d. {end}`` (L11)."""
    return f"{SUBJECT_PREFIX} Status: {result.status.value} — {format_range_id(result.periods.current)}"


def _table(header: str, lines: Iterable[Line], cfg: Config, total: Line | None = None, indent: str = "") -> list[str]:
    rows = [(" / ".join(ln.key), format_idr(ln.cur), format_idr(ln.prior), format_pct(ln.pct_change, cfg.pct_decimals))
            for ln in lines]
    if total is not None:
        rows.append(("TOTAL", format_idr(total.cur), format_idr(total.prior), format_pct(total.pct_change, cfg.pct_decimals)))
    head = (header, "Berjalan", "Sebelumnya", "Ubah")
    widths = [max(len(r[i]) for r in rows + [head]) for i in range(4)]

    def fmt(r: tuple[str, str, str, str]) -> str:
        return indent + "  ".join([r[0].ljust(widths[0])] + [r[i].rjust(widths[i]) for i in (1, 2, 3)]).rstrip()

    out = [fmt(head), indent + "-" * (sum(widths) + 6)]
    out += [fmt(r) for r in rows[: len(rows) - (1 if total is not None else 0)]]
    if total is not None:
        out += [indent + "-" * (sum(widths) + 6), fmt(rows[-1])]
    return out


def _finding_line(f: Finding, cfg: Config) -> str:
    conf = "abu-abu/lower-confidence" if f.confidence is Confidence.LOWER else "normal-confidence"
    text = (
        f"- {f.label}: {format_idr(f.prior)} → {format_idr(f.cur)} "
        f"({format_pct(f.pct_change, cfg.pct_decimals)}) [{conf}]"
    )
    extras = []
    if f.driver_sku:
        extras.append(f"SKU pendorong: {f.driver_sku}")
    if f.recurring_count >= cfg.recurring_min_runs:
        extras.append(f"berulang {f.recurring_count} run berturut-turut")
    if f.note:
        extras.append(f.note)
    return text + ("; " + "; ".join(extras) if extras else "")


def _findings_section(title: str, findings: list[Finding], result: RunResult, cfg: Config) -> list[str]:
    if not findings:
        return []
    out = ["", title]
    for f in findings:
        out.append(_finding_line(f, cfg))
        drill = result.sku_drilldowns.get((f.project_id, f.service_name))
        if drill:
            out += _table("SKU", drill, cfg, indent="    ")
    return out


def build_plain_text(result: RunResult, cfg: Config) -> str:
    """Plain-text email body (L11): status, summary, project and service tables, findings, notes."""
    cur_p, cmp_p = result.periods.current, result.periods.mom
    out = [
        f"Status: {result.status.value}",
        f"Periode berjalan: {format_range_id(cur_p)} ({cur_p.days} hari)",
        f"Periode pembanding: {format_range_id(cmp_p)} ({cmp_p.days} hari)",
        "Mata uang IDR; net cost = cost + credits; periode berdasarkan usage_start_time.",
        "",
        "RINGKASAN",
        result.narrative,
        "",
        "IKHTISAR PROJECT",
    ]
    out += _table("Project", result.project_overview or result.views.get("project", ()), cfg, total=result.total)
    if result.service_breakdown:
        out += ["", f"RINCIAN SERVICE — TOP {len(result.service_breakdown)} PROJECT"]
        for project, lines in result.service_breakdown.items():
            out += ["", project]
            out += _table("Service", lines, cfg, indent="  ")
    rising = [f for f in result.findings if f.type is FindingType.TEMUAN_NAIK]
    drops = [f for f in result.findings if f.type is FindingType.PENURUNAN_BESAR]
    watch = [f for f in result.findings if f.type in (FindingType.WATCHLIST, FindingType.WATCHLIST_NEW_COST)]
    out += _findings_section("TEMUAN YANG DITANDAI", rising, result, cfg)
    out += _findings_section("PENURUNAN BESAR", drops, result, cfg)
    out += _findings_section("DAFTAR PANTAU", watch, result, cfg)
    if not result.findings:
        out += ["", "TEMUAN YANG DITANDAI", "- Tidak ada temuan."]
    for title, notes in (
        ("CATATAN HISTORI", result.history_notes),
        ("CATATAN METODOLOGI", result.methodology_notes),
        ("CATATAN", result.notes),
    ):
        if notes:
            out += ["", title] + [f"- {n}" for n in notes]
    out += [
        "",
        "Laporan ini dihasilkan otomatis dari perhitungan deterministik atas data billing; bukan audit resmi.",
    ]
    return "\n".join(out) + "\n"


def render_technical_view(result: RunResult, cfg: Config) -> str:
    """TODO(WP3): Chat triage message (project -> service -> SKU)."""
    raise NotImplementedError("render_technical_view is scheduled for WP3")


def render_executive_email(result: RunResult, cfg: Config) -> tuple[str, str]:
    """TODO(WP3): return (inline-CSS HTML, plain text) for the executive email.

    The plain-text half already exists as ``build_plain_text`` (WP1b).
    """
    raise NotImplementedError("render_executive_email is scheduled for WP3")


def render_pdf(result: RunResult, cfg: Config) -> bytes:
    """TODO(WP4): PDF archive; size verified before any link is included."""
    raise NotImplementedError("render_pdf is scheduled for WP4")
