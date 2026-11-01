"""Indonesian Rupiah formatting and parsing.

Convention (lessons §8.1): "." is the thousands separator and "," the decimal
separator. ``Rp699.561`` is six hundred ninety-nine thousand, *not* 699 million.
All number formatting is done here, in code; narrative text must never invent
its own shorthand. The validator uses the parsers below to check every amount
that appears in narrative text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

_UNITS: dict[str, Decimal] = {
    "rb": Decimal(10) ** 3,
    "ribu": Decimal(10) ** 3,
    "jt": Decimal(10) ** 6,
    "juta": Decimal(10) ** 6,
    "miliar": Decimal(10) ** 9,
    "milyar": Decimal(10) ** 9,
    "triliun": Decimal(10) ** 12,
}

_MINUS = r"\-\u2212"  # regex class body: escaped hyphen-minus and Unicode minus sign

SHORTHAND_RE = re.compile(
    rf"(?P<neg>[{_MINUS}])?Rp\s?(?P<num>\d{{1,3}}(?:\.\d{{3}})+|\d+)(?:,(?P<dec>\d+))?"
    r"\s*(?P<unit>ribu|rb|juta|jt|miliar|milyar|triliun)\b",
    re.IGNORECASE,
)
FULL_RE = re.compile(
    rf"(?P<neg>[{_MINUS}])?Rp\s?(?P<num>\d{{1,3}}(?:\.\d{{3}})+|\d+)(?:,(?P<dec>\d+))?"
)
PCT_RE = re.compile(rf"(?P<sign>[+{_MINUS}])?(?P<num>\d+)(?:,(?P<dec>\d+))?\s?%")


def round_idr(amount: Decimal | int) -> Decimal:
    """Round to whole Rupiah, half-up."""
    return Decimal(amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _group_thousands(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def format_idr(amount: Decimal | int) -> str:
    """``Decimal('1234567.4')`` -> ``'Rp1.234.567'``; negatives -> ``'-Rp1.234'``."""
    n = int(round_idr(amount))
    return ("-" if n < 0 else "") + "Rp" + _group_thousands(abs(n))


def format_pct(value: Decimal | None, decimals: int = 2, signed: bool = True) -> str:
    """``Decimal('7.1398')`` -> ``'+7,14%'``; ``None`` (prior = 0) -> ``'BARU'``."""
    if value is None:
        return "BARU"
    q = Decimal(1).scaleb(-decimals)
    v = Decimal(value).quantize(q, rounding=ROUND_HALF_UP)
    sign = "+" if signed and v > 0 else ""
    body = f"{abs(v):.{decimals}f}".replace(".", ",")
    return f"{sign}{'-' if v < 0 else ''}{body}%"


@dataclass(frozen=True)
class ParsedAmount:
    text: str
    value: Decimal
    """Absolute value expressed in Rupiah."""
    unit: Decimal
    """Value of one step of the last displayed digit (precision), in Rupiah."""
    negative: bool
    span: tuple[int, int]

    def matches(self, actual: Decimal, tolerance_units: Decimal = Decimal(1)) -> bool:
        """True if ``actual`` is within ``tolerance_units`` x precision (strict).

        With the default of 1 unit, both rounding and truncation are accepted:
        ``Rp699 ribu`` and ``Rp700 ribu`` match 699.561, ``Rp6,9 juta`` does not.
        """
        return abs(abs(actual) - self.value) < self.unit * tolerance_units


def _to_decimal(num: str, dec: str | None) -> Decimal:
    raw = num.replace(".", "") + ("." + dec if dec else "")
    return Decimal(raw)


def parse_shorthand(text: str) -> list[ParsedAmount]:
    """Find shorthand amounts such as ``Rp699 ribu``, ``Rp6,9 juta``, ``Rp2,46 jt``."""
    out: list[ParsedAmount] = []
    for m in SHORTHAND_RE.finditer(text):
        mult = _UNITS[m.group("unit").lower()]
        dec = m.group("dec")
        base = _to_decimal(m.group("num"), dec)
        precision = Decimal(1).scaleb(-len(dec)) if dec else Decimal(1)
        out.append(
            ParsedAmount(
                text=m.group(0),
                value=base * mult,
                unit=precision * mult,
                negative=bool(m.group("neg")),
                span=m.span(),
            )
        )
    return out


def parse_full_amounts(text: str) -> list[ParsedAmount]:
    """Find fully written amounts such as ``Rp47.587.313`` (ignores shorthand spans)."""
    taken = [a.span for a in parse_shorthand(text)]
    out: list[ParsedAmount] = []
    for m in FULL_RE.finditer(text):
        if any(s <= m.start() < e for s, e in taken):
            continue
        dec = m.group("dec")
        out.append(
            ParsedAmount(
                text=m.group(0),
                value=_to_decimal(m.group("num"), dec),
                unit=Decimal(1).scaleb(-len(dec)) if dec else Decimal(1),
                negative=bool(m.group("neg")),
                span=m.span(),
            )
        )
    return out


@dataclass(frozen=True)
class ParsedPct:
    text: str
    value: Decimal
    """Absolute value of the percentage."""
    sign: int
    """+1, -1, or 0 when no explicit sign was written."""
    unit: Decimal

    def matches(self, actual: Decimal) -> bool:
        """Match within half a unit of the last displayed digit; sign checked if written."""
        if self.sign and (actual > 0) != (self.sign > 0) and actual != 0:
            return False
        return abs(abs(actual) - self.value) <= self.unit / 2


def parse_percentages(text: str) -> list[ParsedPct]:
    out: list[ParsedPct] = []
    for m in PCT_RE.finditer(text):
        dec = m.group("dec")
        s = m.group("sign")
        sign = 0 if not s else (1 if s == "+" else -1)
        out.append(
            ParsedPct(
                text=m.group(0),
                value=_to_decimal(m.group("num"), dec),
                sign=sign,
                unit=Decimal(1).scaleb(-len(dec)) if dec else Decimal(1),
            )
        )
    return out
