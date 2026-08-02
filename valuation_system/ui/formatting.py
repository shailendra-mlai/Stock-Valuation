from __future__ import annotations

import math
from typing import Any


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parenthesize(text: str, negative: bool) -> str:
    return f"({text})" if negative else text


def format_currency(value: Any, symbol: str = "$") -> str:
    number = _finite(value)
    if number is None:
        return "—"
    return _parenthesize(f"{symbol}{abs(number):,.2f}", number < 0)


def format_large_currency(value: Any, symbol: str = "$") -> str:
    number = _finite(value)
    if number is None:
        return "—"
    absolute = abs(number)
    if absolute >= 1_000_000:
        text = f"{symbol}{absolute / 1_000_000:,.1f}tn"
    elif absolute >= 1_000:
        text = f"{symbol}{absolute / 1_000:,.1f}bn"
    else:
        text = f"{symbol}{absolute:,.0f}mm"
    return _parenthesize(text, number < 0)


def format_percentage(value: Any) -> str:
    number = _finite(value)
    if number is None:
        return "—"
    return _parenthesize(f"{abs(number):.1%}", number < 0)


def format_multiple(value: Any) -> str:
    number = _finite(value)
    if number is None:
        return "—"
    return _parenthesize(f"{abs(number):.1f}x", number < 0)


def format_number(value: Any, decimals: int = 1) -> str:
    number = _finite(value)
    if number is None:
        return "—"
    return _parenthesize(f"{abs(number):,.{decimals}f}", number < 0)


def format_status(status: str | None) -> str:
    normalized = (status or "UNKNOWN").upper()
    icons = {"PASS": "✅", "WARNING": "⚠️", "FAIL": "❌"}
    return f"{icons.get(normalized, 'ℹ️')} {normalized}"
