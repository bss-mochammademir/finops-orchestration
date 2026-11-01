"""SYNTHETIC fixture for legacy-routine parity rules (WP1b, L2-L10).

Every project id, service amount, SKU and project name in this file is
**SYNTHETIC** (invented for tests, prefix ``syn-``); none of it comes from the
real billing export. It exercises:

- L2  new cost source (BigQuery in syn-prod-a-1) and large absolute rise
      relative to the project (Cloud Run in syn-prod-c-1, +23,3%);
- L3  periodic cost (Cloud Domains, new) and a drop to exactly half
      (Looker Studio Pro in syn-prod-d-1);
- L7  SKU drill-down for the new cost source and the large drop (Cloud SQL in
      syn-prod-b-1);
- L8  watchlist outside top 3: swing (syn-dev-e-1), small new category
      (syn-dev-f-1), storage growth without compute growth (syn-dev-g-1);
- L9  project.name change mid-period (syn-prod-a-1);
- L10 null project row carrying Vertex AI Search;
- L4  sub-threshold recurring rise (syn-dev-h-1) and a known, still-low drop
      (syn-dev-i-1), together with ``legacy_history_v1.json``.

Run mode ``legacy14`` with ``AS_OF`` 2026-11-15: current 2026-11-01..14,
comparison 2026-10-18..31.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from billing_sentinel.domain import CostRow, Period

AS_OF = date(2026, 11, 15)
CUR = Period(date(2026, 11, 1), date(2026, 11, 14))
PRIOR = Period(date(2026, 10, 18), date(2026, 10, 31))

# (project, service, sku) -> (cur, prior)   -- SYNTHETIC
ROWS: dict[tuple[str | None, str, str], tuple[int, int]] = {
    ("syn-prod-a-1", "Compute Engine", "N2 Instance Core"): (5_000_000, 5_000_000),
    ("syn-prod-a-1", "BigQuery", "Analysis"): (300_000, 0),
    ("syn-prod-a-1", "BigQuery", "Active Logical Storage"): (50_000, 0),
    ("syn-prod-b-1", "Compute Engine", "E2 Instance Core"): (3_000_000, 3_000_000),
    ("syn-prod-b-1", "Cloud SQL", "vCPU"): (400_000, 1_200_000),
    ("syn-prod-b-1", "Cloud SQL", "RAM"): (400_000, 800_000),
    ("syn-prod-c-1", "Compute Engine", "E2 Instance Core"): (1_000_000, 1_000_000),
    ("syn-prod-c-1", "Cloud Run", "CPU Allocation Time"): (1_480_000, 1_200_000),
    ("syn-prod-d-1", "Compute Engine", "E2 Instance Core"): (1_000_000, 1_000_000),
    ("syn-prod-d-1", "Cloud Domains", "Domain Registration"): (450_000, 0),
    ("syn-prod-d-1", "Looker Studio Pro", "Subscription"): (1_200_000, 2_400_000),
    ("syn-dev-e-1", "Compute Engine", "E2 Instance Core"): (300_000, 700_000),
    ("syn-dev-f-1", "Compute Engine", "E2 Instance Core"): (400_000, 400_000),
    ("syn-dev-f-1", "Pub/Sub", "Message Delivery Basic"): (50_000, 0),
    ("syn-dev-g-1", "Compute Engine", "E2 Instance Core"): (500_000, 500_000),
    ("syn-dev-g-1", "Cloud Storage", "Standard Storage"): (400_000, 300_000),
    ("syn-dev-h-1", "Cloud Run", "CPU Allocation Time"): (1_100_000, 1_000_000),
    ("syn-dev-i-1", "Cloud SQL", "vCPU"): (600_000, 600_000),
    (None, "Vertex AI Search", "Search Standard"): (20_000, 15_000),
}

# SYNTHETIC project display names; syn-prod-a-1 is renamed mid-period (L9).
NAMES = {"syn-prod-a-1": ("Synthetic A", "Synthetic A Renamed")}

EXPECTED_TOP3 = ("syn-prod-a-1", "syn-prod-b-1", "syn-prod-d-1")


def build_rows() -> list[CostRow]:
    """Each amount is split over the first two days of its period (names differ per day)."""
    rows: list[CostRow] = []
    for (project, service, sku), (c, p) in ROWS.items():
        for start, amount in ((CUR.start, c), (PRIOR.start, p)):
            if amount == 0:
                continue
            half = Decimal(amount) / 2
            for i in range(2):
                names = NAMES.get(project or "")
                name = names[i] if names and start == CUR.start else (names[0] if names else None)
                rows.append(
                    CostRow(
                        charge_date=start + timedelta(days=i),
                        project_id=project,
                        service_name=service,
                        sku_name=sku,
                        gross_cost=half,
                        project_name=name,
                        app_category_code="ac_050" if project else None,
                    )
                )
    return rows
