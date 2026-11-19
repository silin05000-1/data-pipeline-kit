"""REST API client: sends processed data to a configurable HTTP endpoint."""

from __future__ import annotations

import base64
import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import get_secret, require
from .errors import ApiError, ConfigError
from .logging_utils import get_logger

log = get_logger("api")


def build_auth_headers(auth: dict[str, Any]) -> dict[str, str]:
    """Build auth headers; secret values are read from environment variables."""
    if not auth:
        return {}
    kind = str(auth.get("type", "bearer")).lower()

    if kind == "bearer":
        token = get_secret(auth.get("token_env", "API_TOKEN"))
        return {"Authorization": f"Bearer {token}"}

    if kind == "basic":
        username = get_secret(auth.get("username_env", "API_USERNAME"))
        password = get_secret(auth.get("password_env", "API_PASSWORD"))
        raw = f"{username}:{password}".encode()
        return {"Authorization": "Basic " + base64.b64encode(raw).decode()}

    if kind == "header":
        name = require(auth, "name", "api.auth")
        value = get_secret(auth.get("value_env"))
        return {name: value}

    raise ConfigError(f"Unsupported api.auth.type: {kind}")


def build_payload(rows: list[dict[str, Any]], cfg: dict[str, Any], summary: dict[str, Any]) -> Any:
    key = cfg.get("payload_key")
    data = {key: rows} if key else rows
    if not cfg.get("include_meta", True):
        return data
    return {"meta": summary, "data": data}


def send(rows: list[dict[str, Any]], cfg: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any] | None:
    """POST/PUT processed rows to the configured endpoint. Skip if disabled."""
    if not cfg or not cfg.get("enabled", False):
        log.info("API integration disabled — skipping")
        return None

    url = require(cfg, "url", "api")
    method = str(cfg.get("method", "POST")).upper()
    headers = {"Content-Type": "application/json", "User-Agent": "data-pipeline/0.1"}
    headers.update({str(k): str(v) for k, v in (cfg.get("headers") or {}).items()})
    headers.update(build_auth_headers(cfg.get("auth") or {}))

    payload = build_payload(rows, cfg, summary)
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")

    retry = cfg.get("retry") or {}
    attempts = max(1, int(retry.get("attempts", 3)))
    backoff = float(retry.get("backoff", 1.0))
    timeout = int(cfg.get("timeout", 30))
    expected = cfg.get("expect_status") or [200, 201, 202, 204]

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        log.info("API %s %s (attempt %d/%d, %d bytes)", method, url, attempt, attempts, len(body))
        try:
            req = Request(url, data=body, headers=headers, method=method)
            with urlopen(req, timeout=timeout) as resp:
                status = resp.getcode()
                response_body = resp.read(2048).decode("utf-8", errors="replace")
            if status not in expected:
                raise ApiError(f"Unexpected HTTP status {status}, expected {expected}")
            log.info("API call succeeded: HTTP %d", status)
            return {"status": status, "body": response_body[:512]}
        except HTTPError as exc:
            detail = exc.read(512).decode("utf-8", errors="replace")
            last_error = ApiError(f"HTTP {exc.code} from API: {detail[:256]}")
        except (URLError, TimeoutError, OSError) as exc:
            last_error = ApiError(f"Network error calling API: {exc}")
        except ApiError as exc:
            last_error = exc

        if attempt < attempts:
            delay = backoff * (2 ** (attempt - 1))
            log.warning("API attempt %d failed: %s — retry in %.1fs", attempt, last_error, delay)
            time.sleep(delay)

    raise ApiError(f"API call failed after {attempts} attempt(s): {last_error}")
