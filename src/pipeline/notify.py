"""Notifications via Telegram, Slack, SMTP email and generic webhook."""

from __future__ import annotations

import json
import smtplib
from email.message import EmailMessage
from typing import Any
from urllib.request import Request, urlopen

from .config import get_secret, require
from .errors import ConfigError
from .logging_utils import get_logger, redact

log = get_logger("notify")


def build_message(event: str, summary: dict[str, Any], config: dict[str, Any]) -> str:
    status = "✅ УСПЕХ" if event == "success" else "❌ ОШИБКА"
    lines = [
        f"{status} — {config.get('name', 'data pipeline')}",
        f"Строк обработано: {summary.get('rows_out', 0)}",
        f"Источников: {summary.get('sources', 0)}",
        f"Выходной файл: {summary.get('output', '—')}",
    ]
    if summary.get("api_status"):
        lines.append(f"REST API: HTTP {summary['api_status']}")
    if summary.get("error"):
        lines.append(f"Причина: {redact(str(summary['error']))}")
    return redact("\n".join(lines))


def _post_json(url: str, payload: dict[str, Any], timeout: int = 15) -> str:
    req = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "data-pipeline/0.1"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        return str(resp.getcode())


def _telegram(text: str, cfg: dict[str, Any]) -> str:
    token = get_secret(cfg.get("bot_token_env", "TELEGRAM_BOT_TOKEN"))
    chat_id = get_secret(cfg.get("chat_id_env", "TELEGRAM_CHAT_ID"))
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    return _post_json(url, {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})


def _slack(text: str, cfg: dict[str, Any]) -> str:
    webhook = get_secret(cfg.get("webhook_url_env", "SLACK_WEBHOOK_URL"))
    return _post_json(webhook, {"text": text})


def _webhook(text: str, cfg: dict[str, Any]) -> str:
    url = require(cfg, "url", "notify.webhook")
    return _post_json(url, {"event": cfg.get("event"), "text": text, "stats": cfg.get("summary")})


def _email(text: str, cfg: dict[str, Any]) -> str:
    host = require(cfg, "host", "notify.email")
    port = int(cfg.get("port", 587))
    sender = require(cfg, "from", "notify.email")
    recipients = cfg.get("to") or []
    if isinstance(recipients, str):
        recipients = [recipients]
    if not recipients:
        raise ConfigError("notify.email.to must contain at least one address")

    message = EmailMessage()
    message["Subject"] = cfg.get("subject", "Data pipeline report")
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(text)

    username = get_secret(cfg.get("username_env"), required=False)
    password = get_secret(cfg.get("password_env"), required=False)

    if str(cfg.get("use_ssl", False)).lower() in ("true", "1", "yes"):
        client: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=20)
    else:
        client = smtplib.SMTP(host, port, timeout=20)
    with client:
        if str(cfg.get("use_tls", True)).lower() in ("true", "1", "yes") and not cfg.get("use_ssl"):
            client.starttls()
        if username and password:
            client.login(username, password)
        client.send_message(message)
    return "sent"


_CHANNELS = {
    "telegram": _telegram,
    "slack": _slack,
    "email": _email,
    "webhook": _webhook,
}


def notify(event: str, summary: dict[str, Any], config: dict[str, Any]) -> None:
    """Send all configured notifications for an event; never crash the pipeline."""
    if not config:
        return
    events = config.get("on") or ["success", "failure"]
    if event not in events:
        return

    text = build_message(event, summary, config)
    strict = bool(config.get("strict", False))
    failures: list[str] = []

    for name, handler in _CHANNELS.items():
        cfg = config.get(name)
        if not cfg or not cfg.get("enabled", True):
            continue
        channel_cfg = dict(cfg)
        channel_cfg["event"] = event
        channel_cfg["summary"] = summary
        try:
            result = handler(text, channel_cfg)
            log.info("Notification via %s delivered (%s)", name, result)
        except Exception as exc:  # noqa: BLE001 - a failed notification must not lose data
            failures.append(name)
            log.warning("Notification via %s failed: %s", name, exc)

    if failures and strict:
        raise ConfigError("Failed notification channel(s): " + ", ".join(failures))
