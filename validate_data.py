import json, pathlib, datetime
root=pathlib.Path(__file__).resolve().parent
x=json.loads((root/'latest.json').read_text(encoding='utf-8'))
assert x.get('schema')=='FantaSuite.data.v1'
ps=x.get('players',[])
assert len(ps)>=200, f'players insufficienti: {len(ps)}'
ids=[str(p.get('id')) for p in ps]
assert len(ids)==len(set(ids)), 'ID giocatori duplicati'
for p in ps:
    s=p.get('starter_probability',p.get('starter'))
    m=p.get('expected_minutes',p.get('minutes'))
    if s is not None: assert 0<=float(s)<=1
    if m is not None: assert 0<=float(m)<=130
assert isinstance(x.get('fixtures',[]),list)
assert isinstance(x.get('injuries',[]),list)
assert isinstance(x.get('lineups',{}),dict)
assert x.get('source')=='api-football-real', 'provider reale non applicato'
m=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
assert m.get('status')=='real-provider'
print(json.dumps({'valid':True,'players':len(ps),'fixtures':len(x.get('fixtures',[])),
                  'injuries':len(x.get('injuries',[])),'lineups':len(x.get('lineups',{})),
                  'calls':m.get('api_calls_last_run')},ensure_ascii=False))
