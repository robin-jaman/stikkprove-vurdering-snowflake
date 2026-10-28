from __future__ import annotations

from typing import Any

import pandas as pd

DASH = "\u2014"
ELLIPSIS = "\u2026"


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    text = str(value).strip().replace("\xa0", "")
    return text in {"", "-", "nan", "None", "NaT"}


def as_text(value: Any, default: str = DASH) -> str:
    if is_empty(value):
        return default
    return str(value).strip()


def as_flag(value: Any) -> str:
    if is_empty(value):
        return DASH
    text = str(value).strip().lower()
    if text in {"1", "1.0", "true", "ja", "yes"}:
        return "Ja"
    if text in {"0", "0.0", "false", "nei", "no"}:
        return "Nei"
    return as_text(value)


def as_number(value: Any) -> float | None:
    if is_empty(value):
        return None
    if isinstance(value, (int, float)) and not pd.isna(value):
        return float(value)
    text = str(value).strip().replace(" ", "").replace("\xa0", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def format_amount(value: Any) -> str:
    number = as_number(value)
    if number is None:
        return DASH
    if abs(number - round(number)) < 1e-9:
        return f"{number:,.0f}".replace(",", " ")
    return f"{number:,.2f}".replace(",", " ").replace(".", ",", 1)


def format_percent(value: Any) -> str:
    number = as_number(value)
    if number is None:
        return DASH
    text = f"{number:.2f}".replace(".", ",")
    if text.endswith(",00"):
        text = text[:-3]
    return f"{text} %"


def format_delta(value: Any) -> str:
    number = as_number(value)
    if number is None:
        return DASH
    sign = "+" if number > 0 else ""
    return f"{sign}{format_amount(number)}"


def shorten_id(value: Any, keep: int = 8) -> str:
    text = as_text(value, "")
    if not text:
        return DASH
    if len(text) <= keep + 4:
        return text
    return f"{text[:keep]}{ELLIPSIS}"
