#!/usr/bin/env python3
"""Pota data/history: tutto negli ultimi N giorni, poi 1 snapshot al giorno, poi niente.

Uso: python scripts/prune_history.py [--keep-all-days 3] [--keep-daily-days 30] [--dry-run]
I file con nome non riconoscibile non vengono mai toccati.
"""
import argparse
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

HISTORY = Path(__file__).resolve().parents[1] / "data" / "history"
PATTERNS = [
    (re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2})-(\d{2})-(\d{2})"), "%Y %m %d %H %M %S"),  # latest-2026-10-21T13-45-29Z
    (re.compile(r"(\d{4})\.(\d{2})\.(\d{2})\.(\d{2})(\d{2})()"), "%Y %m %d %H %M"),          # 2026.10.20.2006
]


def stamp_of(name):
    for rx, fmt in PATTERNS:
        m = rx.search(name)
        if m:
            parts = [g for g in m.groups() if g != ""]
            try:
                return datetime.strptime(" ".join(parts), fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-all-days", type=int, default=3)
    ap.add_argument("--keep-daily-days", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    now = datetime.now(timezone.utc)
    files = []
    for f in HISTORY.glob("*.json"):
        ts = stamp_of(f.name)
        if ts:
            files.append((ts, f))
    files.sort(reverse=True)  # dal più recente
    seen_days, removed, freed = set(), 0, 0
    for ts, f in files:
        age = now - ts
        if age <= timedelta(days=a.keep_all_days):
            continue
        day = ts.date()
        keep = age <= timedelta(days=a.keep_daily_days) and day not in seen_days
        if keep:
            seen_days.add(day)
            continue
        freed += f.stat().st_size
        removed += 1
        if not a.dry_run:
            f.unlink()
    print(f"{'[dry-run] ' if a.dry_run else ''}rimossi {removed} snapshot, {freed/1e6:.1f} MB; "
          f"restano {len(files)-removed} file datati")


if __name__ == "__main__":
    main()
