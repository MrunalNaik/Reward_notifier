"""Open a visible browser so you can sign in to Microsoft Rewards once.

The session is stored in ./profile and reused by check.py (headless).
Run this again whenever you get a "re-login needed" alert.

Usage:  python login.py
"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

from rewards import browser, config


def main() -> int:
    with sync_playwright() as pw:
        ctx = browser.launch(pw, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(config.REDEEM_URL, wait_until="domcontentloaded")

        print("\nA browser window has opened.")
        print("1. Sign in with your Microsoft account (tick 'Stay signed in').")
        print(f"2. Make sure you end up on {config.REDEEM_URL} and can see the gift cards.")
        input("3. Then press Enter here to save the session and close the browser... ")

        url = page.url
        ok = not browser.is_login_url(url) and "rewards.bing.com" in url
        ctx.close()

    if ok:
        print("Session saved in ./profile. You can now run: python check.py --no-jitter")
        return 0
    print(f"Warning: browser was on {url!r}, which doesn't look like the rewards page. "
          "Sign-in may not have completed; run login.py again.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
