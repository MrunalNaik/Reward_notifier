"""Check Microsoft Rewards India gift cards and alert on new SKUs / restocks.

Usage:
  python check.py               # normal run (random 0-5 min delay first), no login needed
  python check.py --no-jitter   # run immediately
  python check.py --dry-run     # print alerts instead of sending them
  python check.py --test-alert  # send a test notification and exit
  python check.py --browser     # optional: signed-in Playwright mode (adds points balance)
  python check.py --browser --headed   # ...and show the browser

Exit codes: 0 ok, 1 unexpected error, 2 login required, 3 site error, 4 already running.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from rewards import config, db, diff, fetch, notify
from rewards.fetch import LoginRequired, SiteError
from rewards.parser import Card

log = logging.getLogger("check")
LOCK_STALE_SECONDS = 30 * 60


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def setup_logging() -> None:
    config.LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = RotatingFileHandler(config.LOG_DIR / "check.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(fh)
    if sys.stdout is not None:  # pythonw.exe (Task Scheduler) has no console
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        root.addHandler(sh)


def acquire_lock() -> bool:
    try:
        if config.LOCK_FILE.exists() and time.time() - config.LOCK_FILE.stat().st_mtime > LOCK_STALE_SECONDS:
            config.LOCK_FILE.unlink()
        fd = os.open(config.LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False


def release_lock() -> None:
    try:
        config.LOCK_FILE.unlink()
    except FileNotFoundError:
        pass


def load_state() -> dict:
    try:
        return json.loads(config.STATE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        log.warning("state.json is corrupt; starting fresh")
        return {}


def save_state(state: dict) -> None:
    tmp = config.STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, config.STATE_FILE)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def fmt_card(c: Card, balance: int | None) -> str:
    pts = f"{c.points:,} pts" if c.points is not None else "? pts"
    stock = "IN STOCK" if c.in_stock else "out of stock"
    afford = ""
    if balance is not None and c.points is not None and c.in_stock:
        afford = " (you can afford it)" if balance >= c.points else f" (need {c.points - balance:,} more)"
    return f"- {c.name} | {pts} | {stock}{afford}\n  {config.SKU_URL_PREFIX}{c.sku}"


# --------------------------------------------------------------------------- #
# main flow
# --------------------------------------------------------------------------- #
def handle_success(state: dict, result, ts: str, con, dry_run: bool) -> None:
    prev = state.get("cards", {})
    current = list(result.cards)

    # Product pages that failed to load: keep their previous state, so they
    # aren't reported as removed (or later as "new"/"restocked").
    for sku in result.failed_skus:
        if sku in prev and sku not in {c.sku for c in current}:
            old = prev[sku]
            current.append(Card(sku=sku, name=old.get("name", sku), title=old.get("title", ""),
                                points=old.get("points"), in_stock=bool(old.get("in_stock")),
                                eligible=old.get("eligible"), source="carried"))

    first_run = not prev
    changes = diff.compare(prev, current)
    db.log_events(con, ts,
                  [(c.sku, c.name, "new") for c in changes.new]
                  + [(c.sku, c.name, "restocked") for c in changes.restocked]
                  + [(c.sku, c.name, "out_of_stock") for c in changes.gone_oos]
                  + [(s, prev[s].get("name", s), "removed") for s in changes.removed],
                  csv_path=config.EVENTS_CSV)

    in_stock = [c for c in current if c.in_stock]
    log.info("OK: %d cards, %d in stock, balance=%s | new=%d restocked=%d now_oos=%d removed=%d%s",
             len(current), len(in_stock), result.balance, len(changes.new), len(changes.restocked),
             len(changes.gone_oos), len(changes.removed), " (first run)" if first_run else "")

    if first_run and not config.ALERT_ON_FIRST_RUN:
        log.info("First run: saved baseline, no alerts sent.")
    elif changes.alertable:
        parts = []
        if changes.restocked:
            parts.append("BACK IN STOCK:\n" + "\n".join(fmt_card(c, result.balance) for c in changes.restocked))
        if changes.new:
            parts.append("NEW GIFT CARDS:\n" + "\n".join(fmt_card(c, result.balance) for c in changes.new))
        names = [c.title or c.name for c in changes.restocked + changes.new]
        what = names[0] if len(names) == 1 else f"{len(names)} gift cards"
        if not changes.new:
            subject = f"Rewards: {what} back in stock"
        elif not changes.restocked:
            subject = f"Rewards: new - {what}"
        else:
            subject = f"Rewards: {what} new or restocked"
        body = "\n\n".join(parts)
        if result.balance is not None:
            body += f"\n\nYour balance: {result.balance:,} pts"
        body += f"\nRedeem page: {config.GIFTCARDS_URL}\n(checked {ts})"
        first = (changes.restocked + changes.new)[0]
        notify.notify(subject, body, url=config.SKU_URL_PREFIX + first.sku,
                      urgent=True, dry_run=dry_run)

    if state.get("login_alert_sent") or state.get("error_alert_sent"):
        notify.notify("Rewards monitor: working again",
                      f"Checks are succeeding again ({ts}).", dry_run=dry_run)

    state.update({
        "cards": diff.merge(prev, current, ts),
        "last_ok": ts,
        "balance": result.balance,
        "login_alert_sent": False,
        "error_alert_sent": False,
        "consecutive_errors": 0,
    })


def handle_failure(state: dict, status: str, err: str, ts: str, dry_run: bool) -> None:
    if status == "login_required":
        if not state.get("login_alert_sent"):
            sent = notify.notify(
                "Rewards monitor: re-login needed",
                "Your Microsoft Rewards session has expired, so gift-card checks are paused.\n\n"
                f"On your PC run:\n  cd {config.ROOT}\n  .venv\\Scripts\\python login.py\n\n"
                f"Details: {err}\n({ts})", url=config.GIFTCARDS_URL, dry_run=dry_run)
            state["login_alert_sent"] = sent
        return

    n = state.get("consecutive_errors", 0) + 1
    state["consecutive_errors"] = n
    if n >= config.ERROR_ALERT_THRESHOLD and not state.get("error_alert_sent"):
        state["error_alert_sent"] = notify.notify(
            "Rewards monitor: checks failing",
            f"The last {n} checks failed. Latest error ({status}):\n{err}\n\n"
            f"See {config.LOG_DIR / 'check.log'}\n({ts})", dry_run=dry_run)


def scrape_browser(headed: bool):
    # Imported lazily so the default (cloud) mode doesn't need Playwright installed.
    from playwright.sync_api import sync_playwright

    from rewards import browser, scraper
    with sync_playwright() as pw:
        ctx = browser.launch(pw, headless=not headed)
        try:
            return scraper.scrape(ctx)
        finally:
            ctx.close()


def run(args) -> int:
    con = db.connect(config.DB_FILE)
    state = load_state()
    ts = now_iso()
    t0 = time.monotonic()
    status, err, result = "ok", None, None

    try:
        result = scrape_browser(args.headed) if args.browser else fetch.scrape()
    except LoginRequired as e:
        status, err = "login_required", str(e)
    except SiteError as e:
        status, err = "site_error", str(e)
    except Exception as e:
        status, err = "error", f"{type(e).__name__}: {e}"
        log.exception("Unexpected error")

    duration = time.monotonic() - t0
    if status == "ok":
        db.log_check(con, ts=ts, status=status, duration_s=duration, cards=result.cards,
                     balance=result.balance,
                     error=f"failed: {','.join(result.failed_skus)}" if result.failed_skus else None)
        handle_success(state, result, ts, con, args.dry_run)
    else:
        log.warning("%s: %s", status, err)
        db.log_check(con, ts=ts, status=status, duration_s=duration, error=err)
        handle_failure(state, status, err, ts, args.dry_run)

    save_state(state)
    con.close()
    return {"ok": 0, "error": 1, "login_required": 2, "site_error": 3}[status]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-jitter", action="store_true", help="skip the random start delay")
    ap.add_argument("--dry-run", action="store_true", help="print alerts instead of sending")
    ap.add_argument("--browser", action="store_true", help="use the signed-in Playwright browser")
    ap.add_argument("--headed", action="store_true", help="with --browser: show the window")
    ap.add_argument("--test-alert", action="store_true", help="send a test alert and exit")
    args = ap.parse_args()
    setup_logging()

    if args.test_alert:
        ok = notify.notify("Rewards monitor: test alert",
                           "If you can read this, alerts are working.", dry_run=args.dry_run)
        print("Sent." if ok else "Failed: check .env and logs/check.log")
        if ok and config.NTFY_TOPIC and not args.dry_run:
            print(f"ntfy topic: {config.NTFY_TOPIC}")
        return 0 if ok else 1

    if not acquire_lock():
        log.info("Another check is running; exiting.")
        return 4
    try:
        if not args.no_jitter and config.JITTER_MAX_SECONDS > 0:
            delay = random.uniform(0, config.JITTER_MAX_SECONDS)
            log.info("Jitter: sleeping %.0fs", delay)
            time.sleep(delay)
        return run(args)
    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())
