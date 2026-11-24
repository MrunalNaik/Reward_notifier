"""Central configuration: paths and settings loaded from .env."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

PROFILE_DIR = ROOT / "profile"          # persistent browser profile (cookies/session)
SAMPLES_DIR = ROOT / "samples"
STATE_FILE = ROOT / "state.json"
DB_FILE = ROOT / "rewards.db"
LOG_DIR = ROOT / "logs"
EVENTS_CSV = ROOT / "history" / "events.csv"   # restocks/new cards; committed by the cloud job
LOCK_FILE = ROOT / "check.lock"

REDEEM_URL = os.getenv("REDEEM_URL", "https://rewards.bing.com/redeem/in").strip()
GIFTCARDS_URL = os.getenv("GIFTCARDS_URL", REDEEM_URL.rstrip("/") + "/shop").strip()
SKU_URL_PREFIX = "https://rewards.bing.com/redeem/sku/"

# Seconds of random delay before each check (Task Scheduler runs every 20 min).
JITTER_MAX_SECONDS = int(os.getenv("JITTER_MAX_SECONDS", "300"))
# Alert after this many consecutive failed checks (site errors / crashes).
ERROR_ALERT_THRESHOLD = int(os.getenv("ERROR_ALERT_THRESHOLD", "3"))
# Alert for every in-stock card on the very first run (default: silent baseline).
ALERT_ON_FIRST_RUN = os.getenv("ALERT_ON_FIRST_RUN", "0").strip() == "1"
BROWSER_CHANNEL = os.getenv("BROWSER_CHANNEL", "").strip() or None

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh").strip().rstrip("/")

GMAIL_USER =os.getenv("GMAIL_USER", "").strip()
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "")
ALERT_TO = os.getenv("ALERT_TO", "").strip() or GMAIL_USER

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
