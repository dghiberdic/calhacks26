"""Integer euro cents × exact rational rates. Rounding: half away from zero, once, at the cents step."""
from __future__ import annotations

from fractions import Fraction


def rate(x: float | str | Fraction) -> Fraction:
    """Exact rate. Floats go through their shortest repr, so 0.35 is exactly 35/100."""
    if isinstance(x, Fraction):
        return x
    if isinstance(x, int):
        return Fraction(x)
    return Fraction(str(x))


def round_half_up(q: Fraction) -> int:
    n, d = q.numerator, q.denominator
    if n >= 0:
        return (2 * n + d) // (2 * d)
    return -((-2 * n + d) // (2 * d))


def apply_rate(cents: int, r: Fraction) -> int:
    return round_half_up(Fraction(cents) * r)


def eur(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    c = abs(cents)
    return f"{sign}€{c // 100:,}.{c % 100:02d}"


def pct(r: Fraction) -> str:
    return f"{float(r * 100):.4g}%"
