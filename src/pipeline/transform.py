"""Simple assembling / aggregation helpers."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

from .errors import ValidationError
from .logging_utils import get_logger

log = get_logger("transform")

Row = dict[str, Any]


def _numbers(values: list[Any]) -> list[float]:
    result: list[float] = []
    for value in values:
        if value in (None, ""):
            continue
        try:
            result.append(float(value))
        except (TypeError, ValueError):
            continue
    return result


_AGGS: dict[str, Callable[[list[Any], list[Any]], Any]] = {
    "count": lambda values, nums: len([v for v in values if v not in (None, "")]),
    "sum": lambda values, nums: sum(nums) if nums else 0,
    "avg": lambda values, nums: round(sum(nums) / len(nums), 4) if nums else 0,
    "min": lambda values, nums: min(nums) if nums else None,
    "max": lambda values, nums: max(nums) if nums else None,
    "first": lambda values, nums: values[0] if values else None,
    "last": lambda values, nums: values[-1] if values else None,
    "nunique": lambda values, nums: len({str(v) for v in values if v not in (None, "")}),
}


def group_by(rows: list[Row], spec: dict[str, Any]) -> list[Row]:
    """Group rows and compute aggregations.

    Spec example::

        {"by": ["status"], "aggs": {"amount": "sum", "id": "count"}}

    Output column names are ``<field>_<agg>``.
    """
    by = spec.get("by") or []
    aggs = spec.get("aggs") or {}
    if not isinstance(by, list) or not by:
        raise ValidationError("transform.group_by.by must be a non-empty list")

    for func in aggs.values():
        if str(func).lower() not in _AGGS:
            raise ValidationError(
                f"Unknown aggregation '{func}'. Available: {', '.join(_AGGS)}"
            )

    groups: dict[tuple[Any, ...], list[Row]] = defaultdict(list)
    for row in rows:
        groups[tuple(row.get(c) for c in by)].append(row)

    result: list[Row] = []
    for key, members in groups.items():
        out: Row = dict(zip(by, key, strict=False))
        for column, func_name in aggs.items():
            func = _AGGS[str(func_name).lower()]
            values = [r.get(column) for r in members]
            out[f"{column}_{func_name}"] = func(values, _numbers(values))
        result.append(out)

    log.info("Grouped %d rows into %d groups by %s", len(rows), len(result), by)
    return result


def assemble(rows: list[Row], config: dict[str, Any]) -> list[Row]:
    if not config:
        return rows
    if config.get("group_by"):
        return group_by(rows, config["group_by"])
    return rows
