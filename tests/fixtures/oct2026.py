"""Regression fixture: legacy run 18-31 Oct 2026 vs 4-17 Oct 2026.

Provenance
----------
- ``RAW_PROJ`` and ``RAW_TOTAL`` are copied verbatim from
  ``docs/handoff/gcp-billing-alert/prototype/build.py`` (greed-is-good). They are
  per-project net-cost totals already ``ROUND(..., 0)``-ed by the legacy query,
  and the grand total from the same query's ROLLUP.
- The prototype's per-service source (``data.tsv``) is not available. Every
  service-level number below is **SYNTHETIC** — plausible values chosen so that
  the deterministic rules reproduce the prototype's four findings. The only
  service/SKU numbers taken from the prototype text are the Cloud Logging SKUs of
  ``bss-master-network-1`` (Vended Logs Storage Rp318.333 -> Rp316.734 and the new
  "Log Storage cost" Rp461.932) and the *current* Places API SKU amounts of
  ``bss-prod-pdaja-1`` (Atmosphere Data Rp159.281, Contact Data Rp95.568).
- ``CATEGORY_LABELS`` is **SYNTHETIC**: only projects that ADR-003 (doc 03 §2)
  names explicitly as examples are labelled; all others are left unlabelled
  (``UNMAPPED``) so that the coverage test is meaningful.

Rounding tolerance
------------------
sum(RAW_PROJ cur) = 47.587.316 (+3 vs RAW_TOTAL) and sum(RAW_PROJ prior) =
44.416.053 (+1), because each project value was rounded independently. The
prototype asserted |sum - total| <= 40. Here the fixture reconstructs sub-Rupiah
amounts: Rp0,25 is subtracted from the synthetic remainder row of the first 12
(current) / 4 (prior) projects. Each project still rounds (half-up) to exactly its
``RAW_PROJ`` value, and the unrounded grand total equals ``RAW_TOTAL`` exactly.
The displayed (rounded) per-project sum still differs by +3 / +1, which the
validator accepts under the explicit ``[reconciliation] tolerance_idr = 40``
(theoretical maximum for 37 rounded rows is 0,5 x 37 = 18,5).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from billing_sentinel.domain import CostRow, Period, PeriodSet

CUR = Period(date(2026, 10, 18), date(2026, 10, 31))
PRIOR = Period(date(2026, 10, 4), date(2026, 10, 17))
PERIODS = PeriodSet(current=CUR, mom=PRIOR, prior_half=None)
AS_OF = date(2026, 11, 1)

# ---------------------------------------------------------------- verbatim copy
RAW_PROJ = {  # raw per-project totals straight from BigQuery (ROLLUP query)
 'bss-prod-ekyc-2':(7827677,8222838),'bss-master-network-1':(7091750,6593851),'bss-prod-notification-1':(4558896,4649544),
 'bss-mgmt-identity-1':(4076081,4031608),'bss-staging-ekyc-3':(3320383,3350737),'bss-prod-pdaja-1':(3297280,1602757),
 'bss-prod-publicwebsites-1':(2925761,2823324),'bss-prod-digivisit-1':(1936070,0),'bss-prod-easy-1':(1672127,1700063),
 'bss-sandbox-ob-1':(1580061,1788368),'bss-staging-notification-1':(1486555,1398377),'bss-prod-portal-api-1':(1307071,1334164),
 'bss-sandbox-project-1':(1015912,1315010),'bss-prod-diamond-1':(824360,770365),'bss-sandbox-pdaja-2':(752425,832183),
 'bss-staging-csc-1':(644046,656064),'bss-sandbox-bsswebsite-1':(529570,534488),'bss-prod-employeehub-1':(467113,477368),
 'bss-sandbox-superapps-1':(327353,389658),'bss-staging-uam-1':(298094,296015),'bss-staging-digivisit-1':(294815,296475),
 'bss-dev-combstatement-1':(288178,294332),'bss-staging-portal-api-1':(257883,233280),'bss-mgmt-torch-1':(226390,225536),
 'bss-test-phis-1':(203562,234104),'bss-prod-elibrary-1':(198099,203116),'bss-prod-mgmt-1':(84739,58944),
 'bss-prod-analytics-playg-1':(58053,67138),'bss-prod-bdevisa-1':(15079,14445),'bss-partner-storage-ajaib-1':(10330,10559),
 'bss-partner-storage-sandbox':(9061,8884),'bss-sandbox-handover-1':(983,1019),'bss-prod-srm-1':(480,490),
 'bss-prod-trace-1':(477,487),'bss-prod-combstatement-1':(449,460),'bss-sandbox-opb-1':(151,0),'bss-it-spending-analysis':(2,2)}
RAW_TOTAL = (47587313, 44416052)

# ---------------------------------------------------------------- SYNTHETIC
# (project, service, sku) -> (cur, prior). Remainder of each project is put in a
# single synthetic row so project totals stay exactly RAW_PROJ.
REMAINDER_SERVICE = "(synthetic remainder)"
SYNTHETIC_SERVICE_ROWS: dict[tuple[str, str, str], tuple[int, int]] = {
    # Finding 1 (amber, large spike): Maps API > +100% and delta > Rp1.000.000.
    ("bss-prod-pdaja-1", "Maps API", "Dynamic Maps"): (1768320, 121544),
    # Places API: below spike thresholds (+24,1%), not a separate finding.
    ("bss-prod-pdaja-1", "Places API", "Atmosphere Data"): (159281, 128300),
    ("bss-prod-pdaja-1", "Places API", "Contact Data"): (95568, 77016),
    # Finding 2 (amber): Cloud Logging driven by a new SKU.
    ("bss-master-network-1", "Cloud Logging", "Vended Logs Storage"): (316734, 318333),
    ("bss-master-network-1", "Cloud Logging", "Log Storage cost"): (461932, 0),
    # Finding 3 (amber): new cost source, small amount.
    ("bss-master-network-1", "Cloud Run Functions", "Cloud Run functions (1st Gen) CPU Tier 2"): (112640, 0),
    # Finding 4 (grey, lower-confidence): cyclical service.
    ("bss-prod-ekyc-2", "Cloud Monitoring", "Metric Volume"): (612380, 298410),
}

# Only explicit project examples from doc 03 §2 (ADR-003). Everything else: UNMAPPED.
CATEGORY_LABELS: dict[str, str] = {
    "bss-prod-bdevisa-1": "ac_001",
    "bss-sandbox-ob-1": "ac_004",
    "bss-prod-ekyc-2": "ac_005",
    "bss-staging-ekyc-3": "ac_005",
    "bss-prod-pdaja-1": "ac_023",
    "bss-prod-publicwebsites-1": "ac_023",
    "bss-master-network-1": "ac_050",
    "bss-mgmt-identity-1": "ac_050",
    "bss-prod-mgmt-1": "ac_050",
}

EXPECTED_TOP3 = ("bss-prod-ekyc-2", "bss-master-network-1", "bss-prod-notification-1")
EXPECTED_FINDINGS = {
    # (project, service): (type, confidence)
    ("bss-prod-pdaja-1", "Maps API"): ("temuan_naik", "normal"),
    ("bss-master-network-1", "Cloud Logging"): ("temuan_naik", "normal"),
    ("bss-master-network-1", "Cloud Run Functions"): ("temuan_naik", "normal"),
    ("bss-prod-ekyc-2", "Cloud Monitoring"): ("temuan_naik", "lower"),
}

_QUARTER = Decimal("0.25")


def _residual_counts() -> tuple[int, int]:
    cur_excess = sum(v[0] for v in RAW_PROJ.values()) - RAW_TOTAL[0]
    prior_excess = sum(v[1] for v in RAW_PROJ.values()) - RAW_TOTAL[1]
    # Each Rp1 of excess is removed as 4 x Rp0,25 on distinct projects.
    return cur_excess * 4, prior_excess * 4


def build_rows() -> list[CostRow]:
    """CostRows: one row per (project, service, sku) per period.

    Current-period rows are dated ``CUR.start`` and prior rows ``PRIOR.start``
    (no daily shape is available; the lag check is tested separately).
    """
    n_cur, n_prior = _residual_counts()
    assert 0 <= n_cur <= len(RAW_PROJ) and 0 <= n_prior <= len(RAW_PROJ)
    rows: list[CostRow] = []
    for idx, (project, (cur_total, prior_total)) in enumerate(RAW_PROJ.items()):
        label = CATEGORY_LABELS.get(project)
        listed = {k: v for k, v in SYNTHETIC_SERVICE_ROWS.items() if k[0] == project}
        rem_cur = Decimal(cur_total - sum(v[0] for v in listed.values()))
        rem_prior = Decimal(prior_total - sum(v[1] for v in listed.values()))
        if idx < n_cur:
            rem_cur -= _QUARTER
        if idx < n_prior:
            rem_prior -= _QUARTER
        entries = [((s, sku), Decimal(c), Decimal(p)) for (_, s, sku), (c, p) in listed.items()]
        entries.append(((REMAINDER_SERVICE, ""), rem_cur, rem_prior))
        for (service, sku), c, p in entries:
            for day, amount in ((CUR.start, c), (PRIOR.start, p)):
                if amount == 0:
                    continue
                rows.append(
                    CostRow(
                        charge_date=day,
                        project_id=project,
                        service_name=service,
                        sku_name=sku,
                        gross_cost=amount,
                        app_category_code=label,
                        invoice_month="202610",
                    )
                )
    return rows
