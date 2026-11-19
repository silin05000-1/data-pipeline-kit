"""Orchestration of load -> clean -> assemble -> output -> API -> notifications."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import api, cleaner, notify, sources, transform, writers
from .config import load_config
from .errors import PipelineError
from .logging_utils import get_logger, setup_logging

log = get_logger("pipeline")


def _summary(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": config.get("name", "data pipeline"),
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": len(config.get("sources") or []),
        "rows_in": 0,
        "rows_out": 0,
        "output": None,
        "api_status": None,
        "error": None,
    }


def run(
    config_path: str | Path,
    *,
    dry_run: bool = False,
    log_level: str | None = None,
    log_file: str | None = None,
) -> dict[str, Any]:
    """Execute the pipeline and return a JSON-serializable summary."""
    config = load_config(config_path)
    setup_logging(log_level or config.get("log_level", "INFO"), log_file or config.get("log_file"))
    log.info("=== Pipeline '%s' started (dry_run=%s) ===", config.get("name", "unnamed"), dry_run)

    summary = _summary(config)
    started = time.monotonic()
    try:
        rows = sources.load_sources(config)
        summary["rows_in"] = len(rows)

        rows = cleaner.clean(rows, config.get("clean") or {})
        validate_cfg = config.get("validate")
        if validate_cfg is not None:
            cleaner.validate(rows, validate_cfg)

        rows = transform.assemble(rows, config.get("transform") or {})
        summary["rows_out"] = len(rows)

        output_cfg = config.get("output") or {}
        output_path = output_cfg.get("path")
        if output_path:
            if dry_run:
                log.info("Dry run: skipping write to %s", output_path)
                summary["output"] = f"dry-run:{output_path}"
            else:
                writers.write_rows(rows, output_path, output_cfg.get("format", "csv"))
                summary["output"] = str(Path(output_path))
        else:
            summary["output"] = "none"

        if not dry_run:
            response = api.send(rows, config.get("api") or {}, summary)
            if response:
                summary["api_status"] = response["status"]
        else:
            log.info("Dry run: skipping API call and notifications")

        summary["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        summary["duration_ms"] = round((time.monotonic() - started) * 1000)
        if not dry_run:
            notify.notify("success", summary, config.get("notify") or {})
        log.info("=== Pipeline finished in %d ms ===", summary["duration_ms"])
        return summary

    except Exception as exc:  # noqa: BLE001 - failure must be reported and re-raised
        summary["error"] = str(exc)
        summary["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        summary["duration_ms"] = round((time.monotonic() - started) * 1000)
        log.error("Pipeline failed: %s", exc)
        if not dry_run:
            try:
                notify.notify("failure", summary, config.get("notify") or {})
            except Exception as notify_exc:  # noqa: BLE001
                log.warning("Could not send failure notification: %s", notify_exc)
        if isinstance(exc, PipelineError):
            raise
        raise PipelineError(str(exc)) from exc
