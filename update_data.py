import os, json, pathlib, datetime, urllib.parse, urllib.request, urllib.error

ROOT = pathlib.Path(__file__).resolve().parent
LATEST = ROOT / "latest.json"
MANIFEST = ROOT / "manifest.json"
KEY = os.getenv("API_FOOTBALL_KEY", "").strip()
BASE = "https://v3.football.api-sports.io"
LEAGUE = 135
SEASON = 2026
MAX_CALLS = 18
calls = 0

if not KEY:
    raise SystemExit("API_FOOTBALL_KEY non configurata nei repository secrets")


def api(path, **params):
    global calls
    if calls >= MAX_CALLS:
        raise RuntimeError("Limite prudenziale di chiamate raggiunto")
    calls += 1
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "x-apisports-key": KEY,
        "Accept": "application/json",
        "User-Agent": "FantaSuite/8.3"
    })
    with urllib.request.urlopen(req, timeout=30) as res:
        body = json.loads(res.read().decode("utf-8"))
        remaining = res.headers.get("x-ratelimit-requests-remaining")
    errors = body.get("errors") or {}
    if errors:
        raise RuntimeError(f"API error {errors}")
    return body.get("response", []), remaining


def norm(v):
    import unicodedata, re
    v = unicodedata.normalize("NFD", str(v or ""))
    v = "".join(c for c in v if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", v.lower())


def atomic_write(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


old = json.loads(LATEST.read_text(encoding="utf-8"))
now = datetime.datetime.now(datetime.timezone.utc)
today = now.date()
end = today + datetime.timedelta(days=8)
errors = []
remaining = None

# Conserva sempre l'ultima versione valida.
new = dict(old)
new["schema"] = "FantaSuite.data.v1"
new["provider"] = {
    "name": "API-Football / API-Sports",
    "mode": "real",
    "league_id": LEAGUE,
    "season": SEASON
}
new.setdefault("updates", {})

# 1 chiamata aggregata: programma, stati e risultati nelle prossime 8 giornate.
try:
    fixtures, remaining = api("/fixtures", league=LEAGUE, season=SEASON,
                              **{"from": today.isoformat(), "to": end.isoformat()},
                              timezone="Europe/Rome")
    new["fixtures"] = fixtures
except Exception as e:
    errors.append("fixtures: " + str(e))

# 1 chiamata aggregata: indisponibili della data odierna.
try:
    injuries, remaining = api("/injuries", league=LEAGUE, season=SEASON,
                              date=today.isoformat(), timezone="Europe/Rome")
    new["injuries"] = injuries
    # Applica solo indisponibilità esplicitamente restituite dal provider.
    for row in injuries:
        pl = row.get("player") or {}
        name = pl.get("name")
        if not name:
            continue
        reason = pl.get("reason") or pl.get("type") or "Indisponibile secondo API-Football"
        new["updates"][name] = {
            "status": "unavailable",
            "starter": 0,
            "minutes": 0,
            "note": reason,
            "source": "API-Football",
            "updated_at": now.replace(microsecond=0).isoformat()
        }
except Exception as e:
    errors.append("injuries: " + str(e))

# Formazioni ufficiali: al massimo 10 chiamate, soltanto per gare iniziate/finite o imminenti.
lineups = {}
for row in new.get("fixtures", []):
    fx = row.get("fixture") or {}
    fid = fx.get("id")
    status = ((fx.get("status") or {}).get("short") or "")
    ts = fx.get("timestamp")
    if not fid or not ts:
        continue
    kickoff = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
    hours = (kickoff - now).total_seconds() / 3600
    eligible = status not in {"NS", "TBD"} or (-1 <= hours <= 2)
    if not eligible or calls >= 12:
        continue
    try:
        data, remaining = api("/fixtures/lineups", fixture=fid)
        if data:
            lineups[str(fid)] = data
    except Exception as e:
        errors.append(f"lineup {fid}: {e}")
new["lineups"] = lineups

new["updated_at"] = now.replace(microsecond=0).isoformat()
new["source"] = "api-football-real" if calls else old.get("source", "embedded-bootstrap")
new["sync"] = {
    "calls_used_this_run": calls,
    "daily_remaining_header": remaining,
    "errors": errors,
    "successful": not errors or calls > 0
}

# Fallisce solo se non è stato possibile ottenere alcun dato reale.
if errors and not new.get("fixtures") and not new.get("injuries"):
    raise SystemExit("Nessun dato reale acquisito; latest.json precedente preservato. " + " | ".join(errors))

atomic_write(LATEST, new)
manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
manifest.update({
    "schema": "FantaSuite.manifest.v1",
    "updated_at": new["updated_at"],
    "status": "real-provider",
    "provider": "API-Football / API-Sports",
    "api_calls_last_run": calls,
    "api_remaining": remaining,
    "errors": errors,
    "files": {"latest": "latest.json", "league": "league.json"}
})
atomic_write(MANIFEST, manifest)
print(json.dumps({"ok": True, "calls": calls, "fixtures": len(new.get("fixtures", [])),
                  "injuries": len(new.get("injuries", [])), "lineups": len(lineups),
                  "remaining": remaining, "errors": errors}, ensure_ascii=False))
