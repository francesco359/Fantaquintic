import json, pathlib, sys
p=pathlib.Path("data/latest.json")
x=json.loads(p.read_text(encoding="utf-8"))
assert x.get("schema")=="FantaSuite.data.v1"
ps=x.get("players",[])
assert len(ps)>=200
ids=[str(v.get("id")) for v in ps]
assert len(ids)==len(set(ids))
for v in ps:
 s=v.get("starter_probability",v.get("starter"))
 m=v.get("expected_minutes",v.get("minutes"))
 if s is not None: assert 0<=float(s)<=1
 if m is not None: assert 0<=float(m)<=130
print(f"VALID: {len(ps)} players")
