#!/usr/bin/env python3
"""Aggiorna i dati pubblici di FantaSuite/FantaQuintoc.

Output:
  data/fantasuite.json
  data/history/fantasuite-YYYY-MM-DDTHH-MM-SSZ.json

Variabili facoltative:
  FOOTBALL_DATA_API_KEY  Token football-data.org
  FANTASUITE_EXTRA_URLS  URL JSON aggiuntivi separati da virgola
  FANTASUITE_STRICT      1 = termina con errore se nessuna fonte è disponibile
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"
OUTPUT = DATA_DIR / "fantasuite.json"
TIMEOUT = 25
USER_AGENT = "FantaSuite-Updater/2.0 (+GitHub Actions)"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def fetch_json(url: str, headers: dict[str, str] | None = None) -> Any:
    request_headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    request_headers.update(headers or {})
    req = urllib.request.Request(url, headers=request_headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset))


def atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.name}.", delete=False) as tmp:
        tmp.write(text)
        temp_name = Path(tmp.name)
    temp_name.replace(path)


def load_previous() -> dict[str, Any] | None:
    if not OUTPUT.exists():
        return None
    try:
        value = json.loads(OUTPUT.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def compact_match(match: dict[str, Any]) -> dict[str, Any]:
    score = match.get("score") or {}
    full = score.get("fullTime") or {}
    home = match.get("homeTeam") or {}
    away = match.get("awayTeam") or {}
    return {
        "id": match.get("id"),
        "giornata": match.get("matchday"),
        "data_utc": match.get("utcDate"),
        "stato": match.get("status"),
        "casa": {"id": home.get("id"), "nome": home.get("shortName") or home.get("name"), "stemma": home.get("crest")},
        "trasferta": {"id": away.get("id"), "nome": away.get("shortName") or away.get("name"), "stemma": away.get("crest")},
        "risultato": {"casa": full.get("home"), "trasferta": full.get("away")},
        "ultimo_aggiornamento": match.get("lastUpdated"),
    }


def compact_team(team: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": team.get("id"),
        "nome": team.get("shortName") or team.get("name"),
        "sigla": team.get("tla"),
        "stemma": team.get("crest"),
        "stadio": team.get("venue"),
    }


def football_data(token: str) -> dict[str, Any]:
    base = "https://api.football-data.org/v4/competitions/SA"
    headers = {"X-Auth-Token": token}
    competition = fetch_json(base, headers)
    matches = fetch_json(base + "/matches", headers)
    teams = fetch_json(base + "/teams", headers)
    season = competition.get("currentSeason") or {}
    return {
        "competizione": {
            "id": competition.get("id"), "codice": competition.get("code"),
            "nome": competition.get("name"), "stemma": competition.get("emblem"),
        },
        "stagione": {
            "id": season.get("id"), "inizio": season.get("startDate"),
            "fine": season.get("endDate"), "giornata_corrente": season.get("currentMatchday"),
        },
        "squadre": [compact_team(x) for x in teams.get("teams", [])],
        "calendario": [compact_match(x) for x in matches.get("matches", [])],
    }


def main() -> int:
    started = now_utc()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    previous = load_previous()
    errors: list[str] = []
    sources: list[dict[str, Any]] = []
    serie_a: dict[str, Any] = {}
    extras: dict[str, Any] = {}

    token = os.getenv("FOOTBALL_DATA_API_KEY", "").strip()
    if token:
        try:
            serie_a = football_data(token)
            sources.append({"nome": "football-data.org", "stato": "ok"})
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                json.JSONDecodeError, OSError) as exc:
            errors.append(f"football-data.org: {type(exc).__name__}: {exc}")
            sources.append({"nome": "football-data.org", "stato": "errore"})
    else:
        sources.append({"nome": "football-data.org", "stato": "non_configurata"})

    raw_urls = os.getenv("FANTASUITE_EXTRA_URLS", "")
    for index, url in enumerate(filter(None, (x.strip() for x in raw_urls.split(","))), 1):
        key = f"fonte_{index}"
        try:
            extras[key] = fetch_json(url)
            sources.append({"nome": key, "url": url, "stato": "ok"})
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                json.JSONDecodeError, OSError) as exc:
            errors.append(f"{key}: {type(exc).__name__}: {exc}")
            sources.append({"nome": key, "url": url, "stato": "errore"})

    has_fresh_data = bool(serie_a or extras)
    if not has_fresh_data and previous:
        serie_a = previous.get("serie_a", {})
        extras = previous.get("dati_extra", {})

    payload = {
        "schema_version": 2,
        "generato_il": now_utc().isoformat(timespec="seconds").replace("+00:00", "Z"),
        "aggiornamento_riuscito": has_fresh_data,
        "dati_precedenti_mantenuti": bool(not has_fresh_data and previous),
        "fonti": sources,
        "errori": errors,
        "serie_a": serie_a,
        "dati_extra": extras,
        "fantacalcio": {
            "infortunati": extras.get("infortunati", []),
            "squalificati": extras.get("squalificati", []),
            "probabili_formazioni": extras.get("probabili_formazioni", []),
            "giocatori": extras.get("giocatori", []),
        },
    }

    atomic_write(OUTPUT, payload)
    stamp = started.strftime("%Y-%m-%dT%H-%M-%SZ")
    shutil.copy2(OUTPUT, HISTORY_DIR / f"fantasuite-{stamp}.json")

    # Conserva solo gli ultimi 30 snapshot.
    history = sorted(HISTORY_DIR.glob("fantasuite-*.json"), reverse=True)
    for old in history[30:]:
        old.unlink(missing_ok=True)

    print(f"Creato: {OUTPUT.relative_to(ROOT)}")
    print(f"Dati nuovi: {'sì' if has_fresh_data else 'no'}; errori: {len(errors)}")
    if errors:
        for error in errors:
            print(f"AVVISO: {error}", file=sys.stderr)

    strict = os.getenv("FANTASUITE_STRICT", "0").lower() in {"1", "true", "yes"}
    return 1 if strict and not has_fresh_data else 0


if __name__ == "__main__":
    raise SystemExit(main())
