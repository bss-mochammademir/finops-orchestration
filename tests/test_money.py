from decimal import Decimal

from billing_sentinel.money import (
    format_idr,
    format_pct,
    parse_full_amounts,
    parse_percentages,
    parse_shorthand,
)


def test_format_idr_thousands_dot():
    assert format_idr(1234567) == "Rp1.234.567"
    assert format_idr(Decimal("699561.4")) == "Rp699.561"
    assert format_idr(Decimal("0.5")) == "Rp1"  # half-up
    assert format_idr(-9677) == "-Rp9.677"
    assert format_idr(0) == "Rp0"


def test_format_pct_comma_decimal():
    assert format_pct(Decimal("7.139898")) == "+7,14%"
    assert format_pct(Decimal("-2.86"), 1) == "-2,9%"
    assert format_pct(Decimal("63.5"), 2, signed=False) == "63,50%"
    assert format_pct(None) == "BARU"
    assert format_pct(Decimal("0")) == "0,00%"


def test_parse_shorthand_units():
    (a,) = parse_shorthand("biaya Rp699 ribu")
    assert a.value == 699_000 and a.unit == 1_000
    (b,) = parse_shorthand("sekitar Rp6,9 juta")
    assert b.value == 6_900_000 and b.unit == 100_000
    (c,) = parse_shorthand("Rp2,46 jt")
    assert c.value == 2_460_000 and c.unit == 10_000
    (d,) = parse_shorthand("Rp1,2 miliar")
    assert d.value == 1_200_000_000


def test_shorthand_matching_truncation_and_rounding():
    actual = Decimal(699561)
    assert parse_shorthand("Rp699 ribu")[0].matches(actual)
    assert parse_shorthand("Rp700 ribu")[0].matches(actual)
    assert not parse_shorthand("Rp699 juta")[0].matches(actual)
    assert not parse_shorthand("Rp6,9 juta")[0].matches(actual)
    assert parse_shorthand("Rp2,46 jt")[0].matches(Decimal(2463398))


def test_full_amounts_skip_shorthand():
    found = parse_full_amounts("Rp47.587.313 dan Rp699 ribu serta Rp5")
    assert [a.value for a in found] == [47587313, 5]


def test_parse_percentages():
    ps = parse_percentages("naik +7,14% lalu turun -2,9% dan 63,50%")
    assert [(p.value, p.sign) for p in ps] == [(Decimal("7.14"), 1), (Decimal("2.9"), -1), (Decimal("63.50"), 0)]
    assert ps[0].matches(Decimal("7.1398"))
    assert not ps[0].matches(Decimal("-7.14"))
    assert ps[2].matches(Decimal("-63.5"))  # unsigned: compared by magnitude
