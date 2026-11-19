"""Logging setup with automatic redaction of registered secret values."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

_SECRETS: set[str] = set()


def register_secret(value: str | None) -> None:
    """Register a secret so it is replaced with ``***`` in every log record."""
    if value and len(value) >= 3:
        _SECRETS.add(value)


def redact(text: str) -> str:
    """Replace every registered secret with ``***`` in a string."""
    for secret in _SECRETS:
        text = text.replace(secret, "***")
    return text


class SecretRedactingFilter(logging.Filter):
    """Replace known secrets in log messages and arguments."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not _SECRETS:
            return True
        record.msg = redact(str(record.msg))
        if isinstance(record.args, tuple):
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        return True


def setup_logging(level: str = "INFO", log_file: str | None = None) -> logging.Logger:
    logger = logging.getLogger("pipeline")
    logger.handlers.clear()
    logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    logger.propagate = False

    redactor = SecretRedactingFilter()
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    stream.addFilter(redactor)
    logger.addHandler(stream)

    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(fmt)
        file_handler.addFilter(redactor)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"pipeline.{name}")
