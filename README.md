# Microsoft Rewards India – gift card restock monitor

Checks <https://rewards.bing.com/redeem/in/shop> every 20 minutes and sends a
phone notification (ntfy, Telegram or Gmail) when a gift card is **newly
added** or goes from **out of stock → in stock**.

- **No Microsoft login needed.** The gift card pages show stock status to
  signed-out visitors, so plain web requests are enough. There's no browser and
  no stored credentials.
- **Runs in the cloud** on GitHub Actions (free), so your PC can be off.
- **Read-only.** It only sends GET requests and never clicks or redeems anything.

> Automated access may break Microsoft Rewards' terms. This tool is
> low-volume (about 3 page loads every 20 min), but using it is at your own risk.

## How it works

1. Loads the **Gift cards** list (`/redeem/in/shop`) to discover SKUs.
2. Loads each product page (`/redeem/sku/<id>`) and reads the page's embedded
   Next.js data: `price` and `isDisabled` (`true` = "So popular we're
   restocking! Back soon!").
3. Compares with `state.json` and alerts only on new SKUs or restocks.
4. Logs every check to `rewards.db` (SQLite). New cards and restocks are also
   appended to `history/events.csv`.

| Situation | What happens |
|---|---|
| First ever run | Saves a baseline silently (set `ALERT_ON_FIRST_RUN=1` to change this) |
| New SKU / restock | Top-priority notification. Tapping it opens the card's page |
| Card goes out of stock / disappears | Logged, no alert |
| Bing outage page / HTTP 5xx / connection error | Retried twice, then logged as `site_error`. You get an alert only after 3 failures in a row |
| Things recover | One "working again" message |

## 1. Set up notifications (ntfy)

ntfy needs no account or password.

1. Install the free **ntfy** app (Play Store / App Store).
2. Tap **+** → *Subscribe to topic* and enter a long random topic name, e.g.
   `rewards-3f9c2a7e1b5d8046` (server: `ntfy.sh`).

The topic name works like a password: anyone who knows it can see your
alerts. Keep it random and private.

Telegram and Gmail also work (see [Other alert channels](#other-alert-channels)).
Any combination is fine.

## 2. Run it in the cloud with GitHub Actions (recommended)

You need a free GitHub account.

1. **Create a repository** at <https://github.com/new> (e.g. `reward-notifier`).
   Don't add a README or .gitignore. On visibility:
   - **Public**: unlimited free Actions minutes, so every 20 min is fine. The
     code and `history/events.csv` are visible to anyone. Nothing personal is
     in them, and your ntfy topic is stored as a secret.
   - **Private**: 2,000 free minutes/month. Every 20 min uses about 2,200, so
     change the cron line in `.github/workflows/check.yml` to
     `"7,37 * * * *"` (every 30 min, about 1,450 min/month).
2. **Push this folder** (from `C:\projects\reward_notifer`):
   ```powershell
   git add .
   git commit -m "Rewards gift card monitor"
   git remote add origin https://github.com/<your-username>/reward-notifier.git
   git push -u origin main
   ```
   `.env`, `profile/`, `samples/`, `state.json`, `rewards.db` and `logs/` are
   git-ignored and won't be uploaded.
3. **Add your topic as a secret**: repo → *Settings* → *Secrets and variables*
   → *Actions* → **New repository secret** → name `NTFY_TOPIC`, value = your
   topic. Optional: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
4. **Run it once by hand**: *Actions* tab → **Check gift cards** → **Run
   workflow**. Open the run and check the *Check* step log for a line like
   `OK: 2 cards, 1 in stock ... (first run)`.
5. **Test the notifications** with the same **Run workflow** button:
   - tick **Just send a test notification** to check that GitHub can reach your phone;
   - tick **Run a real check but pretend in-stock cards were out of stock** to
     get a real-looking `[TEST] ... back in stock` alert. Nothing fake is saved
     to the history.

After that it runs automatically. Notes:

- GitHub's scheduler often starts runs a few minutes late and occasionally
  skips one under heavy load. That's fine for restocks that last hours, but it
  isn't to-the-minute.
- `state.json` and `rewards.db` are kept in the Actions cache between runs. If
  the cache is ever lost, the next run quietly saves a new baseline.
- To download the full history database: *Actions* → **Check gift cards** →
  **Run workflow** → tick *upload rewards.db* → download the `rewards-db`
  artifact from that run.
- GitHub pauses schedules in repos with no activity for 60 days. The workflow
  makes an empty "keep alive" commit every 45 days to prevent this.
- To stop it: *Actions* → **Check gift cards** → **…** → *Disable workflow*.

## Alternative: run it on your Windows PC

Only runs while the PC is on.

```powershell
cd C:\projects\reward_notifer
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env      # then set NTFY_TOPIC (and/or Telegram/Gmail)
.venv\Scripts\python check.py --test-alert            # test notification
.venv\Scripts\python check.py --no-jitter --dry-run   # real check, prints alerts instead of sending
```

Schedule it every 20 minutes (no admin needed). `check.py` adds a random
0–5 minute delay before each run (`JITTER_MAX_SECONDS`):

```powershell
schtasks /Create /TN "RewardsGiftCardMonitor" /SC MINUTE /MO 20 /F `
  /TR '"C:\projects\reward_notifer\.venv\Scripts\pythonw.exe" "C:\projects\reward_notifer\check.py"'
```

Then in **Task Scheduler** → **RewardsGiftCardMonitor** → *Properties*:
- **Conditions** tab: untick *Start the task only if the computer is on AC power*.
- **Settings** tab: *If the task is already running* → **Do not start a new instance**.

Logs go to `logs\check.log`. Exit codes (Task Scheduler's *Last Run Result*):
`0` OK, `1` unexpected error, `2` login required (browser mode only), `3`
site error, `4` previous check still running. Remove it with
`schtasks /Delete /TN "RewardsGiftCardMonitor" /F`.

Don't run the PC schedule and the cloud workflow at the same time, or you'll
get every alert twice.

### Optional: signed-in browser mode

`check.py --browser` uses a real (headless) Chromium signed in to your
account. Its only advantage is that alerts include your points balance and
"you can afford it". It needs Playwright and a one-time manual login, and only
works on your PC:

```powershell
.venv\Scripts\python -m pip install -r requirements-browser.txt
.venv\Scripts\python -m playwright install chromium
.venv\Scripts\python login.py        # sign in, then press Enter in the terminal
.venv\Scripts\python check.py --browser --no-jitter --dry-run
```

In this mode the browser also blocks every non-GET request to
`rewards.bing.com`, and an expired session sends one "re-login needed" alert.

## Other alert channels

**Telegram:** message **@BotFather** → `/newbot` → copy the token into
`TELEGRAM_BOT_TOKEN`. Send any message to your bot, then open
`https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id` into
`TELEGRAM_CHAT_ID`.

**Gmail (local only):** needs a Google **App Password** (requires 2-Step
Verification) from <https://myaccount.google.com/apppasswords>. An app
password can read your mail as well as send it, so a separate sender-only
Gmail account is safer. Set `GMAIL_USER`, `GMAIL_APP_PASSWORD` and `ALERT_TO`.

## Analysing restock timing

`history/events.csv` (committed to the repo by the cloud job) has
`ts, sku, name, kind`, where kind is `new`, `restocked`, `out_of_stock` or
`removed`. Open it in Excel or Google Sheets.

`rewards.db` has the full detail:

- `checks`: one row per run (`ts`, `status`, `duration_s`, `n_cards`, `n_in_stock`, `balance`, `error`)
- `observations`: one row per card per successful run (`ts`, `sku`, `name`, `points`, `in_stock`)
- `events`: same as the CSV

```sql
-- every restock, newest first
SELECT ts, name FROM events WHERE kind = 'restocked' ORDER BY ts DESC;

-- restocks by hour of day (IST)
SELECT substr(ts, 12, 2) AS hour, count(*) FROM events
WHERE kind = 'restocked' GROUP BY hour ORDER BY hour;

-- how long each restock lasted (restock -> next out_of_stock for the same SKU)
SELECT r.name, r.ts AS restocked,
       (SELECT min(o.ts) FROM events o WHERE o.sku = r.sku AND o.kind = 'out_of_stock' AND o.ts > r.ts) AS sold_out
FROM events r WHERE r.kind = 'restocked' ORDER BY r.ts DESC;

-- check health
SELECT status, count(*) FROM checks GROUP BY status;
```

With checks every ~20 min, timings are accurate to roughly ±25 minutes.

## Files

| Path | Purpose |
|---|---|
| `check.py` | The check: fetch → compare → alert → log |
| `.github/workflows/check.yml` | Cloud schedule (GitHub Actions) |
| `rewards/fetch.py` | Browser-free scraper (default) |
| `rewards/parser.py` | HTML → data parsing (unit-tested) |
| `rewards/diff.py` | New/restock detection |
| `rewards/notify.py` | ntfy, Telegram, Gmail |
| `rewards/db.py` | SQLite + CSV logging |
| `rewards/scraper.py`, `rewards/browser.py`, `login.py` | Optional signed-in browser mode |
| `capture_samples.py` | Saves real pages into `samples/` (browser mode) to debug parser changes |
| `history/events.csv` | Restock history (committed) |
| `state.json`, `rewards.db`, `profile/`, `logs/`, `samples/`, `.env` | Local data – git-ignored |

Run the tests with `.venv\Scripts\python -m pytest -q`.

## If the site changes

If you start getting "checks failing" alerts, look at the *Check* step log in
the Actions run, or at `logs\check.log` locally. Locally,
`python capture_samples.py` (browser mode) saves fresh pages to `samples\`, and
`pytest` checks the parser against them.
