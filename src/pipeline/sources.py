"""Read input data from local files, HTTP(S) URLs or inline rows."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .errors import SourceError
from .logging_utils import get_logger

log = get_logger("sources")

Row = dict[str, Any]


def _read_bytes(source: dict[str, Any]) -> bytes:
    path = source.get("path")
    url = source.get("url")
    if not path and not url:
        raise SourceError("Source must define 'path' or 'url'")

    if url:
        try:
            req = Request(url, headers={"User-Agent": "data-pipeline/0.1"})
            with urlopen(req, timeout=int(source.get("timeout", 30))) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001 - surfaced as SourceError
            raise SourceError(f"Failed to download {url}: {exc}") from exc

    file_path = Path(path)
    if not file_path.is_file():
        raise SourceError(f"Source file not found: {file_path}")
    return file_path.read_bytes()


def _parse_csv(data: bytes, source: dict[str, Any]) -> list[Row]:
    text = data.decode(source.get("encoding", "utf-8-sig"), errors="replace")
    delimiter = source.get("delimiter")
    if not delimiter:
        try:
            delimiter = csv.Sniffer().sniff(text[:4096]).delimiter
        except csv.Error:
            delimiter = ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    rows = [dict(row) for row in reader]
    log.info("Read %d CSV rows (delimiter=%r)", len(rows), delimiter)
    return rows


def _parse_json(data: bytes, source: dict[str, Any]) -> list[Row]:
    text = data.decode(source.get("encoding", "utf-8"), errors="replace")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SourceError(f"Invalid JSON: {exc}") from exc

    key = source.get("root")
    if key:
        payload = payload.get(key, [])

    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list) or not all(isinstance(r, dict) for r in payload):
        raise SourceError("JSON source must be a list of objects")
    log.info("Read %d JSON rows", len(payload))
    return payload


def _parse_jsonl(data: bytes, source: dict[str, Any]) -> list[Row]:
    text = data.decode(source.get("encoding", "utf-8"), errors="replace")
    rows: list[Row] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SourceError(f"Invalid JSONL at line {lineno}: {exc}") from exc
        if not isinstance(obj, dict):
            raise SourceError(f"JSONL line {lineno} is not an object")
        rows.append(obj)
    log.info("Read %d JSONL rows", len(rows))
    return rows


def read_source(source: dict[str, Any]) -> list[Row]:
    """Read a single source definition into a list of dictionaries."""
    name = source.get("name", "unnamed")
    log.info("Reading source '%s'", name)

    if "rows" in source:
        rows = source["rows"]
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise SourceError(f"Inline rows in '{name}' must be objects")
        log.info("Read %d inline rows", len(rows))
        return list(rows)

    raw = _read_bytes(source)
    kind = source.get("type", "csv").lower()
    parsers = {"csv": _parse_csv, "json": _parse_json, "jsonl": _parse_jsonl}
    parser = parsers.get(kind)
    if parser is None:
        raise SourceError(f"Unsupported source type: {kind} (use csv, json, jsonl)")
    return parser(raw, source)


def _join(left: list[Row], right: list[Row], on: str, how: str) -> list[Row]:
    how = how.lower()
    index: dict[Any, Row] = {}
    for row in right:
        index.setdefault(row.get(on), row)

    result: list[Row] = []
    matched: set[int] = set()
    for row in left:
        other = index.get(row.get(on))
        if other is not None:
            merged = {**other, **row}
            result.append(merged)
            matched.add(id(other))
        elif how in ("left", "outer"):
            result.append(dict(row))

    if how in ("right", "outer"):
        left_keys = {r.get(on) for r in left}
        for i, row in enumerate(right):
            if i not in matched and row.get(on) not in left_keys:
                result.append(dict(row))
    return result


def load_sources(config: dict[str, Any]) -> list[Row]:
    """Load and combine every source declared in the config."""
    sources = config.get("sources") or []
    if not sources:
        raise SourceError("No sources defined in config")

    datasets = [read_source(s) for s in sources]
    rows = datasets[0]

    merge_cfg = config.get("merge")
    if merge_cfg:
        for i, other in enumerate(datasets[1:], 1):
            rows = _join(
                rows,
                other,
                on=merge_cfg.get("on", "id"),
                how=merge_cfg.get("how", "left"),
            )
            log.info("Merged source %d by '%s' (%s join) -> %d rows",
                     i, merge_cfg.get("on", "id"), merge_cfg.get("how", "left"), len(rows))
    else:
        rows = [row for dataset in datasets for row in dataset]
        log.info("Concatenated %d sources -> %d rows", len(datasets), len(rows))

    limit = config.get("limit")
    if limit is not None:
        rows = rows[: int(limit)]
        log.info("Limited to %d rows", len(rows))
    return rows
