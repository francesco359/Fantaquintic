import json, pathlib
x=json.loads(pathlib.Path('latest.json').read_text(encoding='utf-8')); assert x.get('schema')=='FantaSuite.data.v1'
ps=x.get('players',[]); assert len(ps)>=200
ids=[str(p.get('id')) for p in ps]; assert len(ids)==len(set(ids))
for p in ps:
 s=p.get('starter_probability',p.get('starter')); m=p.get('expected_minutes',p.get('minutes'))
 if s is not None: assert 0<=float(s)<=1
 if m is not None: assert 0<=float(m)<=130
print('VALID',len(ps))
