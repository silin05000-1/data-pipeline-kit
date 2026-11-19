"""Pure, composable data-cleaning steps over ``list[dict]`` rows."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable

from .errors import ValidationError
from .logging_utils import get_logger

log = get_logger("cleaner")

Row = dict[str, Any]

_HEADER_RE = re.compile(r"[^0-9A-Za-zА-Яа-яЁё]+")


def normalize_headers(rows: list[Row]) -> list[Row]:
    mapping: dict[str, str] = {}
    for row in rows:
        for key in row:
            if key not in mapping:
                mapping[key] = _slug(key)
    if any(old != new for old, new in mapping.items()):
        log.info("Normalized %d headers", sum(old != new for old, new in mapping.items()))
    return [{mapping.get(k, k): v for k, v in row.items()} for row in rows]


def _slug(value: str) -> str:
    slug = _HEADER_RE.sub("_", str(value).strip()).strip("_").lower()
    return slug or "column"


def strip_whitespace(rows: list[Row]) -> list[Row]:
    def clean(value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    return [{k: clean(v) for k, v in row.items()} for row in rows]


def drop_empty_rows(rows: list[Row]) -> list[Row]:
    def is_empty(value: Any) -> bool:
        return value is None or (isinstance(value, str) and not value.strip())

    before = len(rows)
    rows = [row for row in rows if not all(is_empty(v) for v in row.values())]
    if before != len(rows):
        log.info("Dropped %d empty rows", before - len(rows))
    return rows


def rename_columns(rows: list[Row], mapping: dict[str, str]) -> list[Row]:
    if not mapping:
        return rows
    return [{mapping.get(k, k): v for k, v in row.items()} for row in rows]


def drop_columns(rows: list[Row], columns: list[str]) -> list[Row]:
    if not columns:
        return rows
    drop = set(columns)
    return [{k: v for k, v in row.items() if k not in drop} for row in rows]


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "да", "on"}


def _to_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace("/", "-")
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
        return parsed.date().isoformat() if fmt in ("%Y-%m-%d", "%d-%m-%Y") else parsed.isoformat()
    log.warning("Could not parse date: %r", value)
    return None


_CASTERS: dict[str, Callable[[Any], Any]] = {
    "str": str,
    "int": lambda v: int(float(str(v).strip().replace(" ", "").replace(",", "."))),
    "float": lambda v: float(str(v).strip().replace(" ", "").replace(",", ".")),
    "bool": _to_bool,
    "date": _to_date,
}


def cast_values(rows: list[Row], casts: dict[str, str]) -> list[Row]:
    if not casts:
        return rows
    for row in rows:
        for column, target in casts.items():
            if column not in row:
                continue
            value = row[column]
            if value in (None, ""):
                continue
            caster = _CASTERS.get(str(target).lower())
            if caster is None:
                raise ValidationError(f"Unknown cast type '{target}' for column '{column}'")
            try:
                row[column] = caster(value)
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    f"Cannot cast column '{column}' value {value!r} to {target}: {exc}"
                ) from exc
    return rows


def fill_missing(rows: list[Row], fills: dict[str, Any]) -> list[Row]:
    if not fills:
        return rows
    for row in rows:
        for column, default in fills.items():
            value = row.get(column)
            if value is None or (isinstance(value, str) and not value.strip()):
                row[column] = default
    return rows


def _compare(actual: Any, op: str, expected: Any) -> bool:
    op = op.lower()
    try:
        if op in ("gt", "gte", "lt", "lte"):
            a, b = float(actual), float(expected)
            return {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[op]
    except (TypeError, ValueError):
        return False

    if op == "eq":
        return str(actual) == str(expected)
    if op == "ne":
        return str(actual) != str(expected)
    if op == "in":
        return str(actual) in {str(x) for x in (expected or [])}
    if op == "not_in":
        return str(actual) not in {str(x) for x in (expected or [])}
    if op == "contains":
        return str(expected).lower() in str(actual).lower()
    if op == "regex":
        return re.search(str(expected), str(actual)) is not None
    if op == "not_null":
        return actual is not None and str(actual).strip() != ""
    if op == "is_null":
        return actual is None or str(actual).strip() == ""
    raise ValidationError(f"Unknown filter operator '{op}'")


def filter_rows(rows: list[Row], filters: list[dict[str, Any]]) -> list[Row]:
    if not filters:
        return rows
    before = len(rows)
    for rule in filters:
        field = rule.get("field")
        op = rule.get("op", "eq")
        expected = rule.get("value")
        rows = [r for r in rows if _compare(r.get(field), op, expected)]
        log.info("Filter %s %s %s: %d -> %d rows", field, op, expected, before, len(rows))
        before = len(rows)
    return rows


def drop_duplicates(rows: list[Row], by: list[str] | None = None) -> list[Row]:
    seen: set[tuple[Any, ...]] = set()
    result: list[Row] = []
    for row in rows:
        key = tuple(row.get(c) for c in by) if by else tuple(sorted(row.items(), key=lambda x: x[0]))
        if key not in seen:
            seen.add(key)
            result.append(row)
    if len(result) != len(rows):
        log.info("Dropped %d duplicate rows", len(rows) - len(result))
    return result


def validate(rows: list[Row], rules: dict[str, Any]) -> None:
    """Validate rows; raise ValidationError with a short, data-free summary."""
    required = rules.get("required") or []
    if required:
        for i, row in enumerate(rows):
            missing = [c for c in required if row.get(c) in (None, "")]
            if missing:
                raise ValidationError(
                    f"Row {i + 1} is missing required column(s): {', '.join(missing)}"
                )

    patterns = rules.get("regex") or {}
    for column, pattern in patterns.items():
        compiled = re.compile(str(pattern))
        for i, row in enumerate(rows):
            value = row.get(column)
            if value not in (None, "") and not compiled.search(str(value)):
                raise ValidationError(
                    f"Row {i + 1} column '{column}' does not match required pattern"
                )

    unique = rules.get("unique") or []
    for column in unique:
        values = [row.get(column) for row in rows]
        if len(values) != len(set(map(str, values))):
            raise ValidationError(f"Column '{column}' contains duplicate values")

    if rules.get("min_rows") is not None and len(rows) < int(rules["min_rows"]):
        raise ValidationError(
            f"Expected at least {rules['min_rows']} rows, got {len(rows)}"
        )
    log.info("Validation passed for %d rows", len(rows))


def clean(rows: list[Row], options: dict[str, Any]) -> list[Row]:
    """Apply cleaning steps in a deterministic order."""
    rows = [dict(row) for row in rows]
    if options.get("normalize_headers", True):
        rows = normalize_headers(rows)
    if options.get("strip_whitespace", True):
        rows = strip_whitespace(rows)
    if options.get("drop_empty_rows", True):
        rows = drop_empty_rows(rows)
    rows = rename_columns(rows, options.get("rename") or {})
    rows = drop_columns(rows, options.get("drop_columns") or [])
    rows = cast_values(rows, options.get("cast") or {})
    rows = fill_missing(rows, options.get("fill") or {})
    rows = filter_rows(rows, options.get("filters") or [])
    if options.get("drop_duplicates"):
        by = options["drop_duplicates"]
        rows = drop_duplicates(rows, by if isinstance(by, list) else None)
    return rows
