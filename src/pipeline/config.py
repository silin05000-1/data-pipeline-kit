"""Configuration loading, environment substitution and secret handling."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .logging_utils import register_secret

_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _substitute(value: Any, missing: list[str]) -> Any:
    if isinstance(value, dict):
        return {k: _substitute(v, missing) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, missing) for v in value]
    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            if name in os.environ:
                return os.environ[name]
            if default is not None:
                return default
            missing.append(name)
            return f"<unset:{name}>"

        return _PLACEHOLDER.sub(repl, value)
    return value


def load_config(path: str | Path) -> dict[str, Any]:
    """Read a JSON config and resolve ``${ENV_VAR}`` / ``${ENV_VAR:-default}``."""
    file_path = Path(path)
    if not file_path.is_file():
        raise ConfigError(f"Config file not found: {file_path}")

    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {file_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("Config root must be a JSON object")

    missing: list[str] = []
    config = _substitute(raw, missing)
    if missing:
        unique = sorted(set(missing))
        raise ConfigError(
            "Missing environment variables: " + ", ".join(unique) +
            ". See .env.example and export them before running."
        )
    return config


def get_secret(name: str | None, *, required: bool = True) -> str | None:
    """Read a secret from the environment and register it for log redaction."""
    if not name:
        if required:
            raise ConfigError("A required *_env setting is missing in config")
        return None
    value = os.environ.get(name)
    if value:
        register_secret(value)
    elif required:
        raise ConfigError(f"Missing environment variable: {name}")
    return value


def require(config: dict[str, Any], key: str, context: str = "config") -> Any:
    value = config.get(key)
    if value is None or value == "":
        raise ConfigError(f"Missing required '{key}' in {context}")
    return value
