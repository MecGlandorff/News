from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re


NUMBER_PATTERN = re.compile(r"(?<!\w)\d+(?:[.,]\d+)*%?(?!\w)")


def normalized_number_tokens(text: str | None) -> set[str]:
    return {
        token
        for token in (normalize_number_token(value) for value in NUMBER_PATTERN.findall(text or ""))
        if token
    }


def normalize_number_token(value: str) -> str:
    text = str(value or "").strip().rstrip("%")
    if not text:
        return ""

    decimal_separator = _decimal_separator(text)
    normalized = []
    for char in text:
        if char.isdigit():
            normalized.append(char)
        elif char in {",", "."} and char == decimal_separator:
            normalized.append(".")

    candidate = "".join(normalized)
    if not candidate:
        return ""
    return _canonical_decimal(candidate)


def _decimal_separator(text: str) -> str | None:
    separators = [char for char in text if char in {",", "."}]
    if not separators:
        return None

    separator_types = set(separators)
    if len(separator_types) > 1:
        return separators[-1]

    separator = separators[0]
    parts = text.split(separator)
    if len(parts) == 2:
        fractional_part = parts[1]
        if separator == "," and len(fractional_part) == 3:
            return None
        if len(fractional_part) in {1, 2}:
            return separator

    if len(parts) > 2 and all(len(part) == 3 for part in parts[1:]):
        return None
    return separators[-1]


def _canonical_decimal(value: str) -> str:
    try:
        rendered = format(Decimal(value).normalize(), "f")
    except InvalidOperation:
        return value
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"
