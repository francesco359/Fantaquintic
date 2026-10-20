import json
import re
import hashlib
import sys
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.request import Request, urlopen

R = Path(__file__).resolve().parents[1]
C = json.loads((R / "config.json").read_text(encoding="utf-8"))
D = R / "data"
TZ = ZoneInfo(C.get("timezone", "Europe/Rome"))
D.mkdir(parents=True, exist_ok=True)
(D / "history").mkdir(parents=True, exist_ok=True)

def fetch(url):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 FantaSuiteBot/13.2", "Accept-Language": "it-IT"})
    with urlopen(req, timeout=25) as response:
        html = response.read().decode("utf-8", "replace")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))

def kickoff_list():
    return sorted(datetime.fromisoformat(x["kickoff"]).astimezone(TZ) for x in C.get("fixtures", []))

def phase(now):
    games = kickoff_list()
    if not games:
        return "normal"
    if any(k <= now <= k + timedelta(hours=2, minutes=15) for k in games):
        return "live"
    if games[0] - timedelta(hours=3) <= now < games[0]:
        return "pre_match"
    if now > games[-1] + timedelta(hours=2, minutes=15):
        return "post_round"
    return "normal"

def due(now, last, mode):
    if mode == "pre_match": gap = timedelta(minutes=30)
    elif now.weekday() <= 3: gap = timedelta(hours=6)
    elif now.weekday() == 4: gap = timedelta(hours=3)
    else: gap = timedelta(hours=1)
    return last is None or now - last >= gap

def apply_medical(text, payload, source):
    changed = 0
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for p in payload.get("players", []):
        hits = [s for s in sentences if p.get("name", "").lower() in s.lower() and any(w in s.lower() for w in ("infortun", "lesion", "frattur", "risentiment", "dubbio"))]
        if not hits: continue
        sentence = hits[0][:420]
        unavailable = any(w in sentence.lower() for w in ("fuori", "stop", "indisponibile", "lesione", "frattura"))
        p["status"] = "unavailable" if unavailable else "doubt"
        p["note"] = sentence
        p["medical_update"] = {"source": source, "verified_at": datetime.now(TZ).isoformat()}
        if unavailable:
            for key in ("appearance_probability", "starter_probability", "vote_probability", "expected_minutes", "expected_fantasy_average_g8", "surprise_score", "hidden_value"):
                p[key] = 0
        p["surprise_eligible"] = False
        changed += 1
    return changed

def apply_lineups(text, payload):
    changed = 0
    for p in payload.get("players", []):
        match = re.search(re.escape(p.get("name", "")) + r".{0,180}?(\d{1,3})%", text, re.I)
        if match and p.get("status") == "available":
            starter = min(1, int(match.group(1)) / 100)
            p["starter_probability"] = starter
            p["appearance_probability"] = min(.99, starter + .04)
            p["vote_probability"] = min(.99, starter + .02)
            p["expected_minutes"] = round(38 + 48 * starter)
            changed += 1
    return changed

def main(force=False):
    latest = D / "latest.json"
    status_file = D / "status.json"
    payload = json.loads(latest.read_text(encoding="utf-8"))
    old_status = json.loads(status_file.read_text(encoding="utf-8")) if status_file.exists() else {}
    now = datetime.now(TZ)
    last = datetime.fromisoformat(old_status["generated_at"]).astimezone(TZ) if old_status.get("generated_at") else None
    mode = phase(now)
    if not force and not due(now, last, mode):
        print("SKIP: cadenza non ancora raggiunta")
        return
    errors, counts, sources = [], {}, []
    for source in ("injuries_sos", "injuries_sky"):
        url = C.get("sources", {}).get(source)
        if not url: continue
        try:
            counts[source] = apply_medical(fetch(url), payload, source)
            sources.append({"id": source, "name": source, "updated_at": now.isoformat()})
        except Exception as exc:
            errors.append(f"{source}: {exc}")
    if mode not in ("live", "post_round"):
        url = C.get("sources", {}).get("lineups")
        if url:
            try: counts["lineups"] = apply_lineups(fetch(url), payload)
            except Exception as exc: errors.append(f"lineups: {exc}")
    if mode == "post_round":
        url = C.get("sources", {}).get("votes")
        if url:
            try: (D / "votes_snapshot.txt").write_text(fetch(url), encoding="utf-8")
            except Exception as exc: errors.append(f"votes: {exc}")
    payload.update(schema="FantaSuite.full-update.v1", generated_at=now.isoformat(), update_mode=mode, sources=sources, automation={"counts": counts, "errors": errors, "lineups_frozen": mode == "live"})
    raw = json.dumps(payload, ensure_ascii=False, indent=2)
    version = now.strftime("%Y.%m.%d.%H%M")
    (D / "history" / f"{version}.json").write_text(raw, encoding="utf-8")
    latest.write_text(raw, encoding="utf-8")
    status = {"version": version, "generated_at": now.isoformat(), "round": payload.get("round"), "players": len(payload.get("players", [])), "update_mode": mode, "lineups_frozen": mode == "live", "checksum": hashlib.sha256(raw.encode()).hexdigest(), "errors": errors}
    status_file.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False))

if __name__ == "__main__":
    main("--force" in sys.argv)
