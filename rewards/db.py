"""SQLite log of every check, for analysing restock timing later.

Tables
  checks(id, ts, status, duration_s, n_cards, n_in_stock, balance, error)
      status: ok | login_required | site_error | error
  observations(check_id, ts, sku, name, points, in_stock)
      one row per card per successful check
  events(id, ts, sku, name, kind)
      kind: new | restocked | out_of_stock | removed
"""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from .parser import Card

SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    status TEXT NOT NULL,
    duration_s REAL,
    n_cards INTEGER,
    n_in_stock INTEGER,
    balance INTEGER,
    error TEXT
);
CREATE TABLE IF NOT EXISTS observations (
    check_id INTEGER NOT NULL REFERENCES checks(id),
    ts TEXT NOT NULL,
    sku TEXT NOT NULL,
    name TEXT,
    points INTEGER,
    in_stock INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_obs_sku_ts ON observations(sku, ts);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    sku TEXT NOT NULL,
    name TEXT,
    kind TEXT NOT NULL
);
"""


def connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    return con


def log_check(con: sqlite3.Connection, *, ts: str, status: str, duration_s: float,
              cards: list[Card] | None = None, balance: int | None = None,
              error: str | None = None) -> int:
    cards = cards or []
    cur = con.execute(
        "INSERT INTO checks (ts, status, duration_s, n_cards, n_in_stock, balance, error) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ts, status, round(duration_s, 2), len(cards) if cards else None,
         sum(c.in_stock for c in cards) if cards else None, balance, error),
    )
    check_id = cur.lastrowid
    con.executemany(
        "INSERT INTO observations (check_id, ts, sku, name, points, in_stock) VALUES (?, ?, ?, ?, ?, ?)",
        [(check_id, ts, c.sku, c.name, c.points, int(c.in_stock)) for c in cards],
    )
    con.commit()
    return check_id


def log_events(con: sqlite3.Connection, ts: str, rows: list[tuple[str, str, str]],
               csv_path: Path | None = None) -> None:
    """rows: (sku, name, kind). Also appended to csv_path (a small, git-friendly
    history that survives in the repo when running on GitHub Actions)."""
    if not rows:
        return
    con.executemany("INSERT INTO events (ts, sku, name, kind) VALUES (?, ?, ?, ?)",
                    [(ts, sku, name, kind) for sku, name, kind in rows])
    con.commit()
    if csv_path is not None:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not csv_path.exists()
        with csv_path.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["ts", "sku", "name", "kind"])
            w.writerows([(ts, sku, name, kind) for sku, name, kind in rows])
