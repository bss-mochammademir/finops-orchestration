"""Status rules (spec §2 IN.2)."""

from decimal import Decimal

import pytest

from billing_sentinel.classify import border_color, derive_status
from billing_sentinel.domain import Confidence, Finding, FindingType, Status


def F(cur, prior, conf=Confidence.NORMAL, ftype=FindingType.TEMUAN_NAIK, svc="S"):
    return Finding("p", svc, ftype, conf, Decimal(cur), Decimal(prior))


N = Confidence.NORMAL
L = Confidence.LOWER


@pytest.mark.parametrize(
    "findings, expected",
    [
        ([], Status.NORMAL),
        ([F(150, 100, ftype=FindingType.PENURUNAN_BESAR), F(1, 0, ftype=FindingType.WATCHLIST_NEW_COST)], Status.NORMAL),
        ([F(150, 100)], Status.PERLU_PERHATIAN),
        ([F(150, 100), F(150, 100)], Status.PERLU_PERHATIAN),
        ([F(150, 100, L)], Status.PERLU_PERHATIAN),
        ([F(150, 100), F(150, 100), F(150, 100, L), F(150, 100, L)], Status.PERLU_PERHATIAN),
        ([F(150, 100), F(150, 100), F(150, 100)], Status.ANOMALI),
        ([F(2_100_001, 1_000_000)], Status.ANOMALI),  # +110%, delta 1.100.001
        ([F(2_000_000, 1_000_000)], Status.PERLU_PERHATIAN),  # exactly +100%: not > 100
        ([F(900_000, 100_000)], Status.PERLU_PERHATIAN),  # +800% but delta 800.000
        ([F(5_000_000, 1_000_000, L)], Status.PERLU_PERHATIAN),  # lower-confidence spike never escalates
    ],
)
def test_status(findings, expected, cfg):
    assert derive_status(findings, cfg) is expected


def test_status_colors(cfg):
    assert cfg.status_color(Status.NORMAL) == "#2e7d32"
    assert cfg.status_color(Status.PERLU_PERHATIAN) == "#f9a825"
    assert cfg.status_color(Status.ANOMALI) == "#c62828"


def test_lower_confidence_border(cfg):
    assert border_color(F(1, 0, L), cfg) == "#9aa5b1"
    assert border_color(F(1, 0, N), cfg) == "#f9a825"


def test_status_values_never_approval_wording():
    for s in Status:
        assert "setuj" not in s.value.lower() and "approve" not in s.value.lower()
