"""Query filter engine - implements TrueNAS-style query filtering.

Supports: =, !=, >, >=, <, <=, ~ (regex), in, nin, rin, rnin, ^, !^, $, !$
Also supports OR: ["OR", [filter1, filter2]]
"""
import re
from typing import Any


_OPERATORS = {
    "=": lambda v, c: v == c,
    "!=": lambda v, c: v != c,
    ">": lambda v, c: v > c,
    ">=": lambda v, c: v >= c,
    "<": lambda v, c: v < c,
    "<=": lambda v, c: v <= c,
    "~": lambda v, c: re.search(str(c), str(v)) is not None,
    "in": lambda v, c: v in c,
    "nin": lambda v, c: v not in c,
    "rin": lambda v, c: isinstance(v, list) and any(i in c for i in v),
    "rnin": lambda v, c: isinstance(v, list) and not any(i in c for i in v),
    "^": lambda v, c: str(v).startswith(str(c)),
    "!^": lambda v, c: not str(v).startswith(str(c)),
    "$": lambda v, c: str(v).endswith(str(c)),
    "!$": lambda v, c: not str(v).endswith(str(c)),
}


def _get_nested(obj: Any, path: str) -> Any:
    parts = path.split(".")
    for p in parts:
        if obj is None:
            return None
        if isinstance(obj, dict):
            obj = obj.get(p)
        elif isinstance(obj, list) and p.isdigit():
            idx = int(p)
            obj = obj[idx] if idx < len(obj) else None
        else:
            obj = getattr(obj, p, None)
    return obj


def apply_filter(item: Any, filt: list) -> bool:
    if not filt:
        return True

    if filt[0] == "OR":
        return any(apply_filter(item, sub) for sub in filt[1])

    if len(filt) == 3:
        field, op, value = filt
        if op not in _OPERATORS:
            return False
        actual = _get_nested(item, field)
        try:
            return _OPERATORS[op](actual, value)
        except (TypeError, ValueError):
            return False

    return True


def apply_filters(items: list, filters: list) -> list:
    return [item for item in items if apply_filter(item, filters)]


def apply_options(items: list, options: dict) -> list:
    if not options:
        return items

    result = list(items)

    if "select" in options and options["select"]:
        fields = options["select"]
        result = [
            {k: _get_nested(item, k) for k in fields}
            if isinstance(item, dict)
            else item
            for item in result
        ]

    if "order_by" in options:
        for ordering in reversed(options["order_by"]):
            if isinstance(ordering, str):
                desc = ordering.startswith("-")
                field = ordering.lstrip("-")
                result.sort(
                    key=lambda x: (_get_nested(x, field) or "")
                    if not desc
                    else (_get_nested(x, field) or ""),
                    reverse=desc,
                )

    offset = options.get("offset", 0)
    limit = options.get("limit", 0)
    if offset or limit:
        end = offset + limit if limit else None
        result = result[offset:end]

    return result
