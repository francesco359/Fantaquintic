#!/usr/bin/env python3
"""Generatore automatico FantaQuintoc.

Produce e valida:
  data/latest.json
  data/status.json
  data/fantasuite.json
  data/history/latest-*.json

Principi:
- il catalogo completo esistente non viene mai ridotto;
- una fonte raggiungibile non equivale automaticamente a dati acquisiti;
- gli aggiornamenti giocatore sono applicati solo da payload JSON strutturati;
- gli HTML configurati vengono controllati e archiviati come fonti raggiungibili,
  ma non trasformati in percentuali arbitrarie;
- in caso di errore si conserva l'ultimo dataset valido;
- anomalie critiche bloccano la scrittura di latest.json.

Variabili facoltative:
  FOOTBALL_DATA_API_KEY
  FANTASUITE_EXTRA_URLS       URL JSON separati da virgola
  FANTASUITE_STRICT=1         fallisce se nessuna fonte produce dati giocatore
  FANTASUITE_MIN_PLAYERS=490  soglia minima catalogo
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
HISTORY = DATA / "history"
CONFIG = ROOT / "config.json"
LATEST = DATA / "latest.json"
STATUS = DATA / "status.json"
FANTASUITE = DATA / "fantasuite.json"
TIMEOUT = 30
USER_AGENT = "Mozilla/5.0 (compatible; FantaQuintoc-Updater/6.1)"
VALID_STATUS = {"available", "doubt", "unavailable"}
MIN_PLAYERS = int(os.getenv("FANTASUITE_MIN_PLAYERS", "490"))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.name}.", delete=False) as tmp:
        tmp.write(text)
        name = Path(tmp.name)
    name.replace(path)


def fetch(url: str, headers: dict[str, str] | None = None) -> tuple[bytes, str]:
    h = {"User-Agent": USER_AGENT, "Accept": "application/json,text/html;q=0.9,*/*;q=0.8"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        return response.read(), response.headers.get("Content-Type", "")


def fetch_json(url: str, headers: dict[str, str] | None = None) -> Any:
    raw, _ = fetch(url, headers)
    return json.loads(raw.decode("utf-8-sig"))


def normalize_name(value: str) -> str:
    value = value.casefold().replace("ø", "o").replace("ß", "ss")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def player_index(players: list[dict[str, Any]]) -> tuple[dict[int, dict], dict[str, list[dict]]]:
    ids = {int(p["id"]): p for p in players}
    names: dict[str, list[dict]] = {}
    for p in players:
        names.setdefault(normalize_name(str(p.get("name", ""))), []).append(p)
    return ids, names


def resolve_player(record: dict[str, Any], ids: dict[int, dict], names: dict[str, list[dict]]) -> dict | None:
    try:
        pid = int(record.get("id"))
        if pid in ids:
            return ids[pid]
    except (TypeError, ValueError):
        pass
    key = normalize_name(str(record.get("name", "")))
    candidates = names.get(key, [])
    club = str(record.get("club", "")).upper()
    role = str(record.get("role", "")).upper()
    filtered = [p for p in candidates if (not club or p.get("club") == club) and (not role or p.get("role") == role)]
    return filtered[0] if len(filtered) == 1 else (candidates[0] if len(candidates) == 1 else None)


def extract_player_records(payload: Any) -> list[dict[str, Any]]:
    """Accetta gli schemi JSON previsti senza interpretare HTML come dati."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    candidates = [
        payload.get("players"), payload.get("giocatori"),
        (payload.get("fantacalcio") or {}).get("giocatori") if isinstance(payload.get("fantacalcio"), dict) else None,
        payload.get("probabili_formazioni"),
    ]
    for value in candidates:
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return []


def apply_updates(players: list[dict[str, Any]], records: list[dict[str, Any]], source: str) -> tuple[int, list[str]]:
    ids, names = player_index(players)
    applied = 0
    warnings: list[str] = []
    allowed = {"efm", "starter", "appearance", "status", "usual", "surprise", "hidden",
               "reliability", "matchup", "coach", "coachScore", "surpriseEligible"}
    for record in records:
        target = resolve_player(record, ids, names)
        if target is None:
            warnings.append(f"{source}: giocatore non risolto: {record.get('name', record.get('id'))}")
            continue
        changed = False
        for key in allowed:
            if key not in record:
                continue
            value = record[key]
            if key in {"efm", "starter", "appearance", "usual", "surprise", "hidden", "reliability", "matchup", "coachScore"}:
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    warnings.append(f"{source}: {target['name']} {key} non numerico")
                    continue
            if key == "status" and value not in VALID_STATUS:
                warnings.append(f"{source}: {target['name']} status non valido")
                continue
            target[key] = value
            changed = True
        if changed:
            target["updated_by"] = source
            applied += 1
    return applied, warnings


def validate(players: list[dict[str, Any]], previous_count: int) -> list[str]:
    errors: list[str] = []
    if len(players) < MIN_PLAYERS:
        errors.append(f"catalogo incompleto: {len(players)} < {MIN_PLAYERS}")
    if previous_count and len(players) < previous_count:
        errors.append(f"regressione catalogo: {len(players)} < {previous_count}")
    ids: set[int] = set()
    for p in players:
        try:
            pid = int(p["id"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"ID non valido: {p.get('name')}")
            continue
        if pid in ids:
            errors.append(f"ID duplicato: {pid}")
        ids.add(pid)
        name = str(p.get("name", "")).strip()
        if not name or p.get("role") not in {"P", "D", "C", "A"}:
            errors.append(f"anagrafica non valida: {pid}")
        try:
            starter = float(p.get("starter", 0))
            appearance = float(p.get("appearance", 0))
            efm = float(p.get("efm", 0))
        except (TypeError, ValueError):
            errors.append(f"valori non numerici: {pid} {name}")
            continue
        if not 0 <= starter <= 100 or not 0 <= appearance <= 100:
            errors.append(f"probabilità fuori scala: {pid} {name}")
        if starter > appearance:
            errors.append(f"starter > appearance: {pid} {name}")
        status = p.get("status")
        if status not in VALID_STATUS:
            errors.append(f"status non valido: {pid} {name}")
        if status == "unavailable" and (starter != 0 or appearance != 0):
            errors.append(f"indisponibile non azzerato: {pid} {name}")
        if not 0 <= efm <= 15:
            errors.append(f"fantavoto fuori scala: {pid} {name}")
        if "usual" in p:
            p["delta"] = round(float(p["efm"]) - float(p["usual"]), 2)
    return errors


def normalize(players: list[dict[str, Any]]) -> None:
    for p in players:
        p["id"] = int(p["id"])
        p["starter"] = round(max(0.0, min(100.0, float(p.get("starter", 0)))), 1)
        p["appearance"] = round(max(0.0, min(100.0, float(p.get("appearance", 0)))), 1)
        p["efm"] = round(float(p.get("efm", 0)), 2)
        if p.get("status") == "unavailable":
            p["starter"] = p["appearance"] = 0.0
        elif p["appearance"] < p["starter"]:
            p["appearance"] = p["starter"]
        if "usual" in p:
            p["usual"] = round(float(p["usual"]), 2)
            p["delta"] = round(p["efm"] - p["usual"], 2)


def formations(players: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"P": 1, "D": 4, "C": 3, "A": 3}
    def select(kind: str) -> dict[str, Any]:
        result = []
        for role, count in counts.items():
            pool = [p for p in players if p.get("role") == role and p.get("status") != "unavailable" and float(p.get("appearance", 0)) > 0]
            if kind == "best":
                pool.sort(key=lambda p: (float(p.get("efm", 0)), float(p.get("appearance", 0)), float(p.get("starter", 0))), reverse=True)
            else:
                pool = [p for p in pool if p.get("surpriseEligible")]
                pool.sort(key=lambda p: (float(p.get("surprise", 0)), float(p.get("hidden", 0)), float(p.get("efm", 0))), reverse=True)
            result.extend({"id": p["id"], "name": p["name"], "role": p["role"]} for p in pool[:count])
        return {"module": "4-3-3", "players": result}
    return {"best_global_433": select("best"), "surprises_global_433": select("surprise")}


def football_data(token: str) -> dict[str, Any]:
    headers = {"X-Auth-Token": token}
    base = "https://api.football-data.org/v4/competitions/SA"
    competition = fetch_json(base, headers)
    matches = fetch_json(base + "/matches", headers)
    return {"competition": competition, "matches": matches}


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    HISTORY.mkdir(parents=True, exist_ok=True)
    config = read_json(CONFIG, {}) or {}
    previous = read_json(LATEST, {}) or {}
    previous_players = previous.get("players", []) if isinstance(previous.get("players"), list) else []
    if len(previous_players) < MIN_PLAYERS:
        print(f"ERRORE: data/latest.json deve contenere almeno {MIN_PLAYERS} giocatori; trovati {len(previous_players)}", file=sys.stderr)
        return 1

    players = json.loads(json.dumps(previous_players))
    source_log: list[dict[str, Any]] = []
    warnings: list[str] = []
    player_updates = 0
    serie_a: dict[str, Any] = {}
    raw_sources: dict[str, Any] = {}

    token = os.getenv("FOOTBALL_DATA_API_KEY", "").strip()
    if token:
        try:
            serie_a = football_data(token)
            source_log.append({"name": "football-data.org", "status": "ok", "kind": "fixtures"})
        except Exception as exc:
            source_log.append({"name": "football-data.org", "status": "error", "error": f"{type(exc).__name__}: {exc}"})
    else:
        source_log.append({"name": "football-data.org", "status": "not_configured"})

    urls: list[tuple[str, str]] = []
    for name, url in (config.get("sources") or {}).items():
        if isinstance(url, str) and url.startswith("http"):
            urls.append((name, url))
    for i, url in enumerate(filter(None, (x.strip() for x in os.getenv("FANTASUITE_EXTRA_URLS", "").split(","))), 1):
        urls.append((f"extra_{i}", url))

    for name, url in urls:
        try:
            raw, content_type = fetch(url)
            digest = hashlib.sha256(raw).hexdigest()
            entry = {"name": name, "url": url, "status": "reachable", "bytes": len(raw), "sha256": digest}
            is_json = "json" in content_type.lower() or raw.lstrip().startswith((b"{", b"["))
            if is_json:
                payload = json.loads(raw.decode("utf-8-sig"))
                records = extract_player_records(payload)
                applied, notes = apply_updates(players, records, name)
                warnings.extend(notes)
                player_updates += applied
                entry.update({"status": "data_applied" if applied else "json_no_player_updates", "player_updates": applied})
                raw_sources[name] = payload
            else:
                entry["status"] = "html_reachable_not_parsed"
            source_log.append(entry)
        except Exception as exc:
            source_log.append({"name": name, "url": url, "status": "error", "error": f"{type(exc).__name__}: {exc}"})

    normalize(players)
    errors = validate(players, len(previous_players))
    stamp = iso_now()
    round_no = int(config.get("round", previous.get("round", 0) or 0))
    successful_player_update = player_updates > 0

    status = {
        "generated_at": stamp,
        "round": round_no,
        "players": len(players),
        "player_updates": player_updates,
        "fresh_player_data": successful_player_update,
        "sources": source_log,
        "warnings": warnings[:100],
        "errors": errors,
    }
    atomic_json(STATUS, status)

    diagnostic = {
        "schema_version": 3,
        "generated_at": stamp,
        "round": round_no,
        "update_succeeded": not errors and successful_player_update,
        "previous_data_preserved": not successful_player_update,
        "sources": source_log,
        "errors": errors,
        "warnings": warnings[:100],
        "serie_a": serie_a,
        "source_payloads": raw_sources,
    }
    atomic_json(FANTASUITE, diagnostic)

    if errors:
        print("Dataset non pubblicato:", *errors, sep="\n- ", file=sys.stderr)
        return 1

    result = {
        "schema": "FantaSuite.latest.v6.1",
        "generated_at": stamp,
        "round": round_no,
        "players": players,
        "recommended_formations": formations(players),
        "validation": {
            "records": len(players),
            "minimum_required": MIN_PLAYERS,
            "critical_errors": [],
            "fresh_player_data": successful_player_update,
            "player_updates": player_updates,
        },
    }
    atomic_json(LATEST, result)
    history_path = HISTORY / f"latest-{utc_now().strftime('%Y-%m-%dT%H-%M-%SZ')}.json"
    shutil.copy2(LATEST, history_path)
    for old in sorted(HISTORY.glob("latest-*.json"), reverse=True)[30:]:
        old.unlink(missing_ok=True)

    print(f"Creato data/latest.json: {len(players)} giocatori")
    print(f"Aggiornamenti giocatore applicati: {player_updates}")
    if not successful_player_update:
        print("AVVISO: nessuna fonte ha prodotto aggiornamenti giocatore; mantenuto dataset precedente", file=sys.stderr)
    strict = os.getenv("FANTASUITE_STRICT", "0").lower() in {"1", "true", "yes"}
    return 1 if strict and not successful_player_update else 0


if __name__ == "__main__":
    raise SystemExit(main())
