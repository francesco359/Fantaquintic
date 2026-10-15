import json, pathlib, datetime
p=pathlib.Path('latest.json'); x=json.loads(p.read_text(encoding='utf-8'))
x['updated_at']=datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
m=pathlib.Path('manifest.json')
if m.exists():
 y=json.loads(m.read_text(encoding='utf-8')); y['updated_at']=x['updated_at']; y.setdefault('files',{})['latest']='latest.json'; m.write_text(json.dumps(y,ensure_ascii=False,indent=2),encoding='utf-8')
