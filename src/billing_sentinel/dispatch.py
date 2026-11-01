"""Notification dispatcher (ABB A07).

STUB — TODO(WP2): Google Chat incoming webhook with the endpoint resolved from
Secret Manager at runtime (never from config or code), idempotency on
``RunResult.run_id`` (a rerun must not send twice), routing by team/space key
(``ref_project_routing``; no personal names), and fallback to the internal review
space when ``RunResult.route == "review"``. Email (SMTP relay vs Gmail API
``gmail.send``) is decided at gate G4 and implemented in WP3/WP4.
"""

from __future__ import annotations

from .config import Config
from .domain import RunResult


def dispatch(result: RunResult, cfg: Config) -> None:
    """TODO(WP2): send or route to review; record delivery keyed by run_id."""
    raise NotImplementedError("dispatch is scheduled for WP2")


def heartbeat(result: RunResult) -> None:
    """TODO(WP2): record a successful run for the dead man's switch (X03)."""
    raise NotImplementedError("heartbeat is scheduled for WP2")
