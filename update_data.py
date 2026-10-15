import json, pathlib, datetime, os
# Adapter sicuro: aggiorna solo da un JSON autorizzato configurato come secret/provider.
p=pathlib.Path("data/latest.json")
x=json.loads(p.read_text(encoding="utf-8"))
provider=os.getenv("FANTASUITE_PROVIDER_JSON","").strip()
if provider:
 q=pathlib.Path(provider)
 if not q.exists(): raise SystemExit("Provider autorizzato configurato ma file assente")
 incoming=json.loads(q.read_text(encoding="utf-8"))
 if incoming.get("schema")!="FantaSuite.data.v1": raise SystemExit("Schema provider non valido")
 x=incoming
x["updated_at"]=datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding="utf-8")
