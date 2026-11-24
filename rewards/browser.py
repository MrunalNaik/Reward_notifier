"""Shared Playwright helpers: persistent profile launch and login detection.

READ-ONLY: nothing in this project clicks Redeem or submits any form on the
rewards site. Pages are only loaded and read.
"""
from __future__ import annotations

from urllib.parse import urlparse

from playwright.sync_api import BrowserContext, Playwright

from . import config

# Hosts that mean "you are being asked to sign in".
LOGIN_HOSTS = (
    "login.live.com",
    "login.microsoftonline.com",
    "account.live.com",
    "login.microsoft.com",
)


def launch(pw: Playwright, *, headless: bool) -> BrowserContext:
    """Open Chromium/Edge with the persistent profile in ./profile."""
    config.PROFILE_DIR.mkdir(exist_ok=True)
    return pw.chromium.launch_persistent_context(
        user_data_dir=str(config.PROFILE_DIR),
        channel=config.BROWSER_CHANNEL,
        headless=headless,
        locale="en-IN",
        timezone_id="Asia/Kolkata",
        viewport={"width": 1366, "height": 900},
    )


def is_login_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in LOGIN_HOSTS)
