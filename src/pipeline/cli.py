"""Command line interface: ``python -m pipeline``."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .config import load_config
from .errors import ConfigError, PipelineError
from .pipeline import run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline",
        description="Clean and assemble data, send it to a REST API and notify channels.",
    )
    parser.add_argument("-c", "--config", default="config.json", help="Path to JSON config (default: config.json)")
    parser.add_argument("--dry-run", action="store_true", help="Process data but skip output/API/notifications")
    parser.add_argument("--validate-config", action="store_true", help="Only check the config and environment")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Override log level")
    parser.add_argument("--log-file", help="Also write logs to this file")
    parser.add_argument("--summary-json", action="store_true", help="Print the final summary as JSON")
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if args.validate_config:
            print(f"Config OK: {args.config} ({len(config.get('sources') or [])} source(s))")
            return 0

        summary = run(
            args.config,
            dry_run=args.dry_run,
            log_level=args.log_level,
            log_file=args.log_file,
        )
        if args.summary_json:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except (ConfigError, PipelineError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
