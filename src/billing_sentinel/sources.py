"""Cost data sources.

The core only depends on the ``CostSource`` protocol. ``InMemoryCostSource``
backs the tests; the BigQuery adapter is a WP2 stub.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from typing import Protocol, runtime_checkable

from .domain import CostRow


@runtime_checkable
class CostSource(Protocol):
    def fetch(self, start: date, end: date) -> Sequence[CostRow]:
        """Return all ``fact_daily_cost`` rows with ``start <= charge_date <= end``."""
        ...


class InMemoryCostSource:
    """Fixture-backed source. Rows are filtered by ``charge_date`` only."""

    def __init__(self, rows: Iterable[CostRow]) -> None:
        self._rows = tuple(rows)

    def fetch(self, start: date, end: date) -> Sequence[CostRow]:
        return tuple(r for r in self._rows if start <= r.charge_date <= end)


class BigQueryCostSource:
    """Read-only adapter over ``fact_daily_cost`` (see ``sql/``).

    TODO(WP2): implement with the BigQuery client library under a dedicated
    read-only service account (``bigquery.dataViewer`` + ``bigquery.jobUser``),
    always filtering on the ``charge_date`` partition. Must be dry-run
    (``bq query --dry_run``) and byte-scanned checked before use.
    """

    def __init__(self, table: str) -> None:
        self.table = table

    def fetch(self, start: date, end: date) -> Sequence[CostRow]:
        raise NotImplementedError("BigQueryCostSource is scheduled for WP2")
