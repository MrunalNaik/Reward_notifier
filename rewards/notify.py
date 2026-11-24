"""Alerts via Gmail SMTP (app password) and optionally Telegram.

Failures are logged and swallowed so a broken channel never crashes a check.
Returns True if at least one channel delivered.
"""
from __future__ import annotations

import json
import logging
import smtplib
import ssl
import urllib.parse
import urllib.request
from email.message import EmailMessage

from . import config

log = logging.getLogger(__name__)


def send_email(subject: str, body: str) -> bool:
    if not (config.GMAIL_USER and config.GMAIL_APP_PASSWORD and config.ALERT_TO):
        log.warning("Email not configured (GMAIL_USER / GMAIL_APP_PASSWORD / ALERT_TO).")
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config.GMAIL_USER
    msg["To"] = config.ALERT_TO
    msg.set_content(body)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as s:
            s.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
            s.send_message(msg)
        return True
    except Exception:
        log.exception("Email send failed")
        return False


def send_telegram(text: str) -> bool:
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        return False
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text[:4000],
        "disable_web_page_preview": "true",
    }).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=30) as r:
            return bool(json.load(r).get("ok"))
    except Exception:
        log.exception("Telegram send failed")
        return False


def send_ntfy(title: str, body: str, *, url: str | None = None, urgent: bool = False) -> bool:
    """Push notification via ntfy (https://ntfy.sh) - no account or password needed.

    Anyone who knows the topic name can read/send to it, so the topic should be
    long and random (login.py / README explain how to pick one).
    """
    if not config.NTFY_TOPIC:
        return False
    payload = {
        "topic": config.NTFY_TOPIC,
        "title": title,
        "message": body[:3900],
        "priority": 5 if urgent else 3,
        "tags": ["gift"] if urgent else ["bell"],
    }
    if url:
        payload["click"] = url  # tapping the notification opens this page
    req = urllib.request.Request(
        config.NTFY_SERVER + "/",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return 200 <= r.status < 300
    except Exception:
        log.exception("ntfy send failed")
        return False


def any_channel_configured() -> bool:
    return bool(config.NTFY_TOPIC
                or (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)
                or (config.GMAIL_USER and config.GMAIL_APP_PASSWORD))


def notify(subject: str, body: str, *, url: str | None = None, urgent: bool = False,
           dry_run: bool = False) -> bool:
    """Send to every configured channel. url = page to open when tapped."""
    if dry_run:
        print(f"\n[DRY RUN] would send alert:\n  Subject: {subject}\n" +
              "\n".join("  " + line for line in body.splitlines()))
        return True
    if not any_channel_configured():
        log.warning("No alert channel configured in .env (NTFY_TOPIC, Telegram or Gmail).")
        return False
    results = [send_ntfy(subject, body, url=url, urgent=urgent)]
    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        results.append(send_telegram(f"{subject}\n\n{body}"))
    if config.GMAIL_USER and config.GMAIL_APP_PASSWORD:
        results.append(send_email(subject, body))
    return any(results)
