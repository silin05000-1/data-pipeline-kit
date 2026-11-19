"""Write processed rows to disk."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .errors import PipelineError
from .logging_utils import get_logger

log = get_logger("writers")

Row = dict[str, Any]


def write_rows(rows: list[Row], path: str, fmt: str = "csv") -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fmt = fmt.lower()

    if fmt == "csv":
        if not rows:
            out.write_text("", encoding="utf-8")
        else:
            columns: list[str] = []
            for row in rows:
                for key in row:
                    if key not in columns:
                        columns.append(key)
            with out.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
    elif fmt in ("json", "jsonl"):
        with out.open("w", encoding="utf-8") as handle:
            if fmt == "json":
                json.dump(rows, handle, ensure_ascii=False, indent=2, default=str)
                handle.write("\n")
            else:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    else:
        raise PipelineError(f"Unsupported output format: {fmt}")

    log.info("Wrote %d rows to %s (%s)", len(rows), out, fmt)
    return out
