#!/usr/bin/env python3
"""Aggiornamento dati FantaQuintoc.

Rispetto alla versione precedente:
- indici dei nomi/alias costruiti UNA volta (prima venivano ricostruiti, rileggendo
  player_aliases.json da disco, per ogni giocatore del consenso);
- download delle fonti in parallelo, con retry e timeout;
- un giocatore conta come "aggiornato" solo se un valore cambia davvero;
- latest.json e snapshot in history/ vengono scritti solo se i dati sono cambiati;
- formazioni per tutti i moduli (oltre a 4-3-3 e al 4-3-3 "sorprese" che il frontend già legge);
- controlli di salute: parser rotti, fonti irraggiungibili, calendario scaduto.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from html_sources import parse_source  # noqa: E402
from expectation_model import recalculate_all  # noqa: E402

ROOT = Path(os.getenv("FANTASUITE_ROOT") or Path(__file__).resolve().parents[1])
DATA = ROOT / "data"
HISTORY = DATA / "history"
LATEST = DATA / "latest.json"
STATUS = DATA / "status.json"
FANTASUITE = DATA / "fantasuite.json"
CONFIG = ROOT / "config.json"
ALIASES = DATA / "player_aliases.json"
MINUTE_PROFILES = DATA / "player_minutes_profiles.json"

MIN_PLAYERS = int(os.getenv("FANTASUITE_MIN_PLAYERS", "490"))
ALLOWED_FIELDS = (
    "efm", "starter", "appearance", "status", "usual", "surprise", "hidden",
    "reliability", "matchup", "coach", "coachScore", "surpriseEligible", "reason",
    "availability_type", "expected_return",
)
DEFAULT_CONSENSUS = {
    "min_sources": 2,             # fonti minime per un consenso
    "max_spread": 30,             # se le fonti divergono di più, il dato è bloccato
    "single_bench_max": 49,       # una sola fonte può solo mandare in panchina...
    "single_bench_min_drop": 20,  # ...e solo se il calo rispetto a prima è almeno questo
    "unavailable_override_min": 75,  # per riportare disponibile un indisponibile serve titolarità >= 75
}
MODULES = {
    "3-4-3": (3, 4, 3), "3-5-2": (3, 5, 2), "4-3-3": (4, 3, 3), "4-4-2": (4, 4, 2),
    "4-5-1": (4, 5, 1), "5-3-2": (5, 3, 2), "5-4-1": (5, 4, 1),
}
OK_STATUSES = {"extracted", "data_applied", "reachable_no_updates"}


# ----------------------------------------------------------------------------- utilità
def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as f:
        f.write(text)
        tmp = Path(f.name)
    tmp.replace(path)


def norm(s) -> str:
    s = str(s or "").casefold().replace("ø", "o")
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def variants(s) -> set[str]:
    parts = norm(s).split()
    out = {" ".join(parts)}
    if len(parts) > 1:
        out |= {parts[0], parts[-1], " ".join(reversed(parts))}
    return {x for x in out if len(x) > 1}


# ----------------------------------------------------------------------------- rete
def fetch_with_retry(url: str, attempts: int = 3, timeout: int = 20):
    """Ritorna (raw, content_type, tentativi, ms). Solleva l'ultima eccezione se falliscono tutti."""
    last = None
    started = time.perf_counter()
    for i in range(1, attempts + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 FantaQuintoc/7.0", "Accept": "text/html,application/json"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(), r.headers.get("Content-Type", ""), i, int((time.perf_counter() - started) * 1000)
        except Exception as ex:  # noqa: BLE001 - si riprova su qualsiasi errore di rete
            last = ex
            if i < attempts:
                time.sleep(1.5 * i)
    raise last  # type: ignore[misc]


def fetch_all(sources: dict) -> dict:
    def one(item):
        name, url = item
        try:
            return name, {"ok": True, "result": fetch_with_retry(url)}
        except Exception as ex:  # noqa: BLE001
            return name, {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    if not sources:
        return {}
    with ThreadPoolExecutor(max_workers=min(8, len(sources))) as pool:
        return dict(pool.map(one, sources.items()))


# ----------------------------------------------------------------------------- associazione giocatori
def build_indexes(players):
    ids = {int(p["id"]): p for p in players}
    names: dict[str, list] = {}
    unique_alias: dict[str, set] = {}
    for p in players:
        for k in variants(p["name"]):
            names.setdefault(k, []).append(p)
    doc = load(ALIASES, {}) or {}
    for item in doc.get("players", []):
        try:
            p = ids[int(item["id"])]
        except (KeyError, TypeError, ValueError):
            continue
        for alias in item.get("aliases", []):
            names.setdefault(norm(alias), []).append(p)
        for alias in item.get("unique_aliases", []):
            unique_alias.setdefault(norm(alias), set()).add(int(p["id"]))
    for k, v in names.items():
        names[k] = list({int(p["id"]): p for p in v}.values())
    return ids, names, unique_alias


def resolve(rec, ids, names, unique_alias):
    try:
        rid = int(rec.get("id"))
        if rid in ids:
            return ids[rid]
    except (TypeError, ValueError):
        pass
    keys = variants(rec.get("name", ""))
    found = []
    for k in keys:
        found += names.get(k, [])
    candidates = list({int(p["id"]): p for p in found}.values())
    if rec.get("role"):
        candidates = [p for p in candidates if p.get("role") == rec["role"]]
    club = rec.get("club")
    same = [p for p in candidates if club and p.get("club") == club]
    if len(same) == 1:
        return same[0]
    unique_ids = set()
    for k in keys:
        unique_ids |= unique_alias.get(k, set())
    unique = [p for p in candidates if int(p["id"]) in unique_ids]
    if len(unique) == 1:
        return unique[0]
    if not club and len(candidates) == 1:
        return candidates[0]
    return None


def apply_fields(player, rec, source, stamp) -> bool:
    """Scrive solo i campi che cambiano davvero. True se il giocatore è cambiato."""
    changed = False
    for k in ALLOWED_FIELDS:
        if k in rec and player.get(k) != rec[k]:
            player[k] = rec[k]
            changed = True
    if changed:
        player["updated_by"] = source
        player["updated_at"] = stamp
    return changed


# ----------------------------------------------------------------------------- consenso formazioni
def decide(vals, previous, cfg):
    """vals: percentuali di titolarità, una per fonte. Ritorna (valore|None, regola, confidenza)."""
    if len(vals) >= cfg["min_sources"]:
        if max(vals) - min(vals) > cfg["max_spread"]:
            return None, "spread_exceeded", None
        final = sorted(vals)[len(vals) // 2] if len(vals) >= 3 else sum(vals) / len(vals)
        return round(final, 1), "consensus", "high" if len(vals) >= 3 else "medium"
    fresh = vals[0]
    # Una sola fonte non può promuovere un titolare: può solo correggere un vecchio dato alto in panchina.
    if fresh <= cfg["single_bench_max"] and previous - fresh >= cfg["single_bench_min_drop"]:
        return fresh, "single_source_bench_downgrade", "low"
    return None, "only_one_source", None


# ----------------------------------------------------------------------------- normalizzazione / validazione
def normalize(players):
    for p in players:
        p["id"] = int(p["id"])
        p["efm"] = round(float(p.get("efm", 0)), 2)
        p["starter"] = round(max(0, min(100, float(p.get("starter", 0)))), 1)
        p["appearance"] = round(max(0, min(100, float(p.get("appearance", 0)))), 1)
        if p.get("status") == "unavailable":
            p["starter"] = p["appearance"] = 0.0
        elif p["appearance"] < p["starter"]:
            p["appearance"] = p["starter"]
        if "usual" in p:
            p["usual"] = round(float(p["usual"]), 2)
            p["delta"] = round(p["efm"] - p["usual"], 2)


def add_frontend_aliases(players):
    """Campi che la scheda "XI Globali" dell'index.html legge (starter_probability, ecc.)."""
    for p in players:
        p["starter_probability"] = round(p["starter"] / 100, 3)
        p["appearance_probability"] = round(p["appearance"] / 100, 3)
        p["expected_fantasy_average"] = p.get("expected_fantavote", p["efm"])
        p["surprise_score"] = p.get("surprise", 0)


def validate(players, old_count):
    errors = []
    if len(players) < MIN_PLAYERS:
        errors.append(f"catalogo incompleto {len(players)}")
    if len(players) < old_count:
        errors.append("regressione catalogo")
    seen = set()
    for p in players:
        if p["id"] in seen:
            errors.append(f"ID duplicato {p['id']}")
        seen.add(p["id"])
        if not 0 <= p["starter"] <= p["appearance"] <= 100:
            errors.append(f"probabilità {p['id']}")
        if p.get("status") == "unavailable" and (p["starter"] or p["appearance"]):
            errors.append(f"indisponibile {p['id']}")
    return errors


# ----------------------------------------------------------------------------- formazioni
def role_pools(players, key, pred=lambda p: True):
    pools = {}
    for r in "PDCA":
        pools[r] = sorted(
            (p for p in players if p.get("role") == r and p.get("status") != "unavailable"
             and p.get("appearance", 0) > 0 and pred(p)),
            key=lambda p: (key(p), p["appearance"]), reverse=True,
        )
    return pools


def pick(pools, key, module):
    d, c, a = MODULES[module]
    chosen = pools["P"][:1] + pools["D"][:d] + pools["C"][:c] + pools["A"][:a]
    return {
        "module": module,
        "score": round(sum(key(p) for p in chosen), 2),
        "complete": len(chosen) == 1 + d + c + a,
        "players": [{"id": p["id"], "name": p["name"], "role": p["role"]} for p in chosen],
    }


def formations(players):
    best_key = lambda p: p.get("formation_index", p["efm"])  # noqa: E731
    sur_key = lambda p: p.get("surprise", 0)  # noqa: E731
    pools = role_pools(players, best_key)
    by_module = {m: pick(pools, best_key, m) for m in MODULES}
    complete = [x for x in by_module.values() if x["complete"]]
    overall = max(complete, key=lambda x: x["score"]) if complete else by_module["4-3-3"]
    sur = pick(role_pools(players, sur_key, lambda p: bool(p.get("surpriseEligible"))), sur_key, "4-3-3")
    slim = lambda x: {"module": x["module"], "players": x["players"]}  # noqa: E731
    return {
        "best_global_433": slim(by_module["4-3-3"]),
        "surprises_global_433": slim(sur),
        "best_overall": overall,
        "best_by_module": by_module,
    }


# ----------------------------------------------------------------------------- salute
def health_warnings(cfg, old_status, logs, lineup_ok):
    warnings = []
    prev = {s.get("name"): s for s in (old_status or {}).get("sources", []) if isinstance(s, dict)}
    for s in logs:
        name = s.get("name")
        if name == "lineup_consensus":
            continue
        if s.get("status") == "error":
            warnings.append(f"fonte_irraggiungibile:{name}")
        elif s.get("status") == "unsupported":
            warnings.append(f"fonte_senza_parser:{name}")
        elif s.get("records_extracted", 0) == 0 and (prev.get(name, {}).get("records_extracted") or 0) > 0:
            warnings.append(f"parser_rotto:{name}")  # prima estraeva record, ora zero
    if lineup_ok < DEFAULT_CONSENSUS["min_sources"]:
        warnings.append(f"consenso_formazioni_impossibile:{lineup_ok}_fonti_valide")
    kickoffs = []
    for fx in cfg.get("fixtures", []):
        try:
            kickoffs.append(datetime.fromisoformat(fx["kickoff"]))
        except (KeyError, ValueError):
            pass
    if kickoffs and max(kickoffs).timestamp() < time.time() - 4 * 3600:
        warnings.append("config_calendario_scaduto:aggiornare_round_e_fixtures")
    return warnings


# ----------------------------------------------------------------------------- main
def main() -> int:
    t0 = time.perf_counter()
    cfg = load(CONFIG, {}) or {}
    cons = {**DEFAULT_CONSENSUS, **(cfg.get("consensus") or {})}
    old = load(LATEST, {}) or {}
    old_status = load(STATUS, {}) or {}
    old_players = old.get("players", [])
    if len(old_players) < MIN_PLAYERS:
        print("latest.json incompleto", file=sys.stderr)
        return 1

    players = json.loads(json.dumps(old_players))
    stamp = now()
    ids, names, unique_alias = build_indexes(players)  # una volta sola
    sources = cfg.get("sources") or {}
    downloads = fetch_all(sources)

    logs, unmatched, votes = [], [], {}
    total_changed = 0
    lineup_ok = 0
    for name, url in sources.items():
        dl = downloads[name]
        if not dl["ok"]:
            logs.append({"name": name, "url": url, "status": "error", "error": dl["error"]})
            continue
        raw, _ctype, attempts, ms = dl["result"]
        try:
            parsed = parse_source(name, raw.decode("utf-8", "replace"))
        except Exception as ex:  # noqa: BLE001
            logs.append({"name": name, "url": url, "status": "error", "error": f"parse {type(ex).__name__}: {ex}"})
            continue
        base = {"name": name, "url": url, "records_extracted": len(parsed["records"]),
                "source_updated_at": parsed.get("updated_at"), "attempts": attempts, "fetch_ms": ms,
                "sha256": hashlib.sha256(raw).hexdigest()}
        kind = parsed.get("kind")
        if kind == "unsupported":
            logs.append({**base, "status": "unsupported", "players_updated": 0})
        elif kind == "lineups":
            resolved = 0
            for r in parsed["records"]:
                player = resolve(r, ids, names, unique_alias)
                if not player:
                    unmatched.append(f"{name}:{r.get('name')}")
                    continue
                votes.setdefault(int(player["id"]), {})[name] = float(r["starter"])
                resolved += 1
            lineup_ok += 1 if resolved else 0
            logs.append({**base, "status": "extracted" if parsed["records"] else "reachable_no_updates",
                         "records_resolved": resolved, "players_updated": 0})
        else:
            changed = 0
            for r in parsed["records"]:
                p = resolve(r, ids, names, unique_alias)
                if not p:
                    unmatched.append(f"{name}:{r.get('name', r.get('id'))}")
                elif apply_fields(p, r, name, stamp):
                    changed += 1
            total_changed += changed
            logs.append({**base, "status": "data_applied" if parsed["records"] else "reachable_no_updates",
                         "players_updated": changed})

    # ---- consenso formazioni: i giocatori sono già risolti per ID, nessun indice da ricostruire
    consensus_changed, details, blocked, single_evidence = 0, [], [], []
    for pid, by_source in votes.items():
        player = ids[pid]
        value, rule, confidence = decide(list(by_source.values()), float(player.get("starter", 0)), cons)
        if value is None:
            blocked.append({"id": pid, "name": player["name"], "reason": rule, "sources": by_source})
            continue
        was_unavailable = player.get("status") == "unavailable"
        if was_unavailable and value < cons["unavailable_override_min"]:
            # Una fonte infortuni dice "fuori": le formazioni non lo riportano disponibile se non lo danno titolare.
            blocked.append({"id": pid, "name": player["name"], "reason": "unavailable_conflict",
                            "starter": value, "sources": by_source})
            continue
        rec = {"starter": value}
        if was_unavailable:
            rec["status"] = "available"
        if value <= 49:
            rec["appearance"] = min(float(player.get("appearance", 100)), value + 35)
        previous = player.get("starter")
        if apply_fields(player, rec, f"lineup_{rule}", stamp):
            consensus_changed += 1
            details.append({"id": pid, "name": player["name"], "club": player.get("club"), "starter": value,
                            "previous_starter": previous, "confidence": confidence, "rule": rule,
                            "sources": by_source})
            if rule == "single_source_bench_downgrade":
                single_evidence.append(pid)
    total_changed += consensus_changed
    logs.append({"name": "lineup_consensus", "status": "data_applied" if consensus_changed else "insufficient_consensus",
                 "players_updated": consensus_changed, "configured_sources": sum(1 for n in sources if "lineups" in n),
                 "minimum_sources": cons["min_sources"], "maximum_spread": cons["max_spread"],
                 "single_source_bench_updates": len(single_evidence), "sample": details[:40],
                 "blocked_sample": blocked[:40]})

    # ---- modello dei minuti, normalizzazione, validazione
    profiles = (load(MINUTE_PROFILES, {}) or {}).get("profiles", {})
    for p in players:
        prof = profiles.get(str(p["id"]))
        if isinstance(prof, dict):
            p["minutes_profile"] = prof
    normalize(players)  # prima riallinea titolarità/presenza: il modello dei minuti le usa
    recalculate_all(players)
    normalize(players)
    add_frontend_aliases(players)
    errors = validate(players, len(old_players))
    rnd = int(cfg.get("round", old.get("round", 0)))

    sources_ok = sum(1 for s in logs if s.get("status") in OK_STATUSES and s.get("records_extracted", 0) > 0)
    warnings = health_warnings(cfg, old_status, logs, lineup_ok)
    unchanged = (not errors) and players == old_players and rnd == old.get("round")
    status = {
        "generated_at": stamp, "round": rnd, "players": len(players),
        "player_updates": total_changed, "fresh_player_data": total_changed > 0,
        "data_confirmed": sources_ok > 0, "sources_ok": sources_ok, "sources_total": len(sources),
        "latest_rewritten": (not unchanged) and not errors, "sources": logs,
        "unmatched": unmatched[:150], "warnings": warnings, "errors": errors,
        "duration_ms": int((time.perf_counter() - t0) * 1000),
    }
    write(STATUS, status)
    write(FANTASUITE, {"schema_version": 8, "generated_at": stamp,
                       "aggiornamento_riuscito": sources_ok > 0 and not errors,
                       "dati_precedenti_mantenuti": sources_ok == 0, "giocatori_cambiati": total_changed,
                       "fonti": logs, "errori": errors, "avvisi": warnings, "non_associati": unmatched[:150]})
    if errors:
        return 1
    if sources_ok == 0:
        print("Nessuna fonte utilizzabile: dati precedenti mantenuti", file=sys.stderr)
        return 3  # fa fallire il workflow => GitHub invia la notifica

    if not unchanged:
        result = {"schema": "FantaSuite.latest.v6.9", "generated_at": stamp, "round": rnd, "players": players,
                  "recommended_formations": formations(players),
                  "validation": {"records": len(players), "critical_errors": [], "player_updates": total_changed,
                                 "fresh_player_data": total_changed > 0, "canonical_lineup_matching": True}}
        write(LATEST, result)
        HISTORY.mkdir(parents=True, exist_ok=True)
        shutil.copy2(LATEST, HISTORY / f"latest-{stamp.replace(':', '-')}.json")
    print(f"OK {len(players)} giocatori, {total_changed} cambiati, {sources_ok}/{len(sources)} fonti, "
          f"{'dati riscritti' if not unchanged else 'nessun cambiamento'}, "
          f"{len(warnings)} avvisi, {status['duration_ms']} ms")
    for w in warnings:
        print("AVVISO", w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
