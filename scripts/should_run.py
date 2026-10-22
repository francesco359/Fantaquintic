#!/usr/bin/env python3
"""Decide se l'aggiornamento va eseguito ora, in base alla vicinanza dei calci d'inizio.

Il workflow gira ogni 30 minuti ma questo gate lo fa lavorare davvero solo quando serve:
  - da 3 ore prima a 3 ore dopo un calcio d'inizio ... ogni 30 minuti
  - nelle 24 ore prima della prima partita ........... ogni 60 minuti
  - nelle 72 ore prima ............................... ogni 2 ore
  - altrimenti ....................................... ogni 6 ore
Scrive run=true|false su $GITHUB_OUTPUT. Un avvio manuale (workflow_dispatch) esegue sempre.
Usa solo la libreria standard.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOLERANCE_MIN = 5  # il cron di GitHub ha qualche minuto di jitter


def parse_ts(s):
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def interval_minutes(kickoffs, now):
    deltas_h = [(k - now).total_seconds() / 3600 for k in kickoffs]
    if any(-3 <= d <= 3 for d in deltas_h):
        return 30
    upcoming = [d for d in deltas_h if d > 3]
    nxt = min(upcoming) if upcoming else None
    if nxt is not None and nxt <= 24:
        return 60
    if nxt is not None and nxt <= 72:
        return 120
    return 360


def main():
    now = datetime.now(timezone.utc)
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8")) if (ROOT / "config.json").exists() else {}
    kickoffs = [k for k in (parse_ts(f.get("kickoff")) for f in cfg.get("fixtures", [])) if k]
    interval = interval_minutes(kickoffs, now)
    forced = os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch"
    age_min = None
    try:
        last = parse_ts(json.loads((ROOT / "data" / "status.json").read_text(encoding="utf-8"))["generated_at"])
        age_min = (now - last).total_seconds() / 60
    except Exception:
        pass
    run = forced or age_min is None or age_min >= interval - TOLERANCE_MIN
    print(f"intervallo={interval}min età_ultimo={'n/d' if age_min is None else round(age_min)}min "
          f"forzato={forced} -> run={str(run).lower()}")
    out = os.getenv("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"run={str(run).lower()}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
