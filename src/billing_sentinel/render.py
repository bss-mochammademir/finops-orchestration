"""Two-view renderer (ABB A06): inline-CSS HTML email, plain-text body, PDF archive.

STUB — TODO(WP3/WP4): technical view (project -> service -> SKU) for Google Chat
in WP3; executive view per ADR-003 ``ac_xxx`` (names joined from
``ref_app_category`` only, never hard-coded), inline ``style=""`` HTML plus a
plain-text body (lessons §8.8), and PDF to Cloud Storage in WP3/WP4.
"""

from __future__ import annotations

from .config import Config
from .domain import RunResult


def render_technical_view(result: RunResult, cfg: Config) -> str:
    """TODO(WP3): Chat triage message (project -> service -> SKU)."""
    raise NotImplementedError("render_technical_view is scheduled for WP3")


def render_executive_email(result: RunResult, cfg: Config) -> tuple[str, str]:
    """TODO(WP3): return (inline-CSS HTML, plain text) for the executive email."""
    raise NotImplementedError("render_executive_email is scheduled for WP3")


def render_pdf(result: RunResult, cfg: Config) -> bytes:
    """TODO(WP4): PDF archive; size verified before any link is included."""
    raise NotImplementedError("render_pdf is scheduled for WP4")
