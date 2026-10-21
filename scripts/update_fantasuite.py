#!/usr/bin/env python3
"""Aggiorna FantaQuintoc da fonti HTML/JSON senza API obbligatorie."""
from __future__ import annotations
import hashlib,json,os,re,shutil,sys,tempfile,urllib.request
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
from html_sources import parse_source
ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'data';HISTORY=DATA/'history'
LATEST=DATA/'latest.json';STATUS=DATA/'status.json';FANTASUITE=DATA/'fantasuite.json';CONFIG=ROOT/'config.json'
MIN_PLAYERS=int(os.getenv('FANTASUITE_MIN_PLAYERS','490'));VALID={'available','doubt','unavailable'}
def now():return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
def load(p,d=None):
 try:return json.loads(p.read_text(encoding='utf-8'))
 except Exception:return d
def write(p,x):
 p.parent.mkdir(parents=True,exist_ok=True);text=json.dumps(x,ensure_ascii=False,indent=2)+'\n'
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=p.parent,delete=False) as f:f.write(text);n=Path(f.name)
 n.replace(p)
def fetch(url):
 req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 FantaQuintoc/6.2','Accept':'text/html,application/json'})
 with urllib.request.urlopen(req,timeout=35) as r:return r.read(),r.headers.get('Content-Type','')
def norm(s):return re.sub(r'[^a-z0-9]+',' ',str(s).casefold().replace('ø','o')).strip()
def indexes(players):
 ids={int(p['id']):p for p in players};names={}
 for p in players:names.setdefault(norm(p['name']),[]).append(p)
 return ids,names
def resolve(r,ids,names):
 try:
  if int(r.get('id')) in ids:return ids[int(r['id'])]
 except Exception:pass
 c=names.get(norm(r.get('name','')),[]);club=r.get('club')
 if club:c=[p for p in c if p.get('club')==club]
 return c[0] if len(c)==1 else None
def records_json(x):
 if isinstance(x,list):return [z for z in x if isinstance(z,dict)]
 if not isinstance(x,dict):return []
 for k in ('players','giocatori','probabili_formazioni'):
  if isinstance(x.get(k),list):return x[k]
 f=x.get('fantacalcio');return f.get('giocatori',[]) if isinstance(f,dict) else []
def apply(players,records,source):
 ids,names=indexes(players);n=0;unmatched=[]
 for r in records:
  p=resolve(r,ids,names)
  if not p:unmatched.append(r.get('name',r.get('id')));continue
  changed=False
  for k in ('efm','starter','appearance','status','usual','surprise','hidden','reliability','matchup','coach','coachScore','surpriseEligible','reason','availability_type'):
   if k not in r:continue
   v=r[k]
   if k in ('efm','starter','appearance','usual','surprise','hidden','reliability','matchup','coachScore'):
    try:v=float(v)
    except Exception:continue
   if k=='status' and v not in VALID:continue
   p[k]=v;changed=True
  if changed:p['updated_by']=source;p['updated_at']=now();n+=1
 return n,unmatched
def normalize(players):
 for p in players:
  p['id']=int(p['id']);p['efm']=round(float(p.get('efm',0)),2)
  p['starter']=round(max(0,min(100,float(p.get('starter',0)))),1);p['appearance']=round(max(0,min(100,float(p.get('appearance',0)))),1)
  if p.get('status')=='unavailable':p['starter']=p['appearance']=0.0
  elif p['appearance']<p['starter']:p['appearance']=p['starter']
  if 'usual'in p:p['usual']=round(float(p['usual']),2);p['delta']=round(p['efm']-p['usual'],2)
def validate(ps,oldn):
 e=[]
 if len(ps)<MIN_PLAYERS:e.append(f'catalogo incompleto: {len(ps)} < {MIN_PLAYERS}')
 if len(ps)<oldn:e.append(f'regressione catalogo: {len(ps)} < {oldn}')
 ids=set()
 for p in ps:
  if p['id'] in ids:e.append(f"ID duplicato {p['id']}")
  ids.add(p['id'])
  if p.get('role') not in 'PDCA' or p.get('status') not in VALID:e.append(f"anagrafica/stato {p['id']}")
  if not 0<=p['starter']<=p['appearance']<=100:e.append(f"probabilità {p['id']}")
  if p['status']=='unavailable' and (p['starter'] or p['appearance']):e.append(f"indisponibile {p['id']}")
 return e
def formations(ps):
 out=[]
 for r,c in {'P':1,'D':4,'C':3,'A':3}.items():
  pool=sorted((p for p in ps if p['role']==r and p['status']!='unavailable' and p['appearance']>0),key=lambda p:(p['efm'],p['appearance']),reverse=True)[:c]
  out += [{'id':p['id'],'name':p['name'],'role':r} for p in pool]
 return {'best_global_433':{'module':'4-3-3','players':out}}
def main():
 cfg=load(CONFIG,{}) or {};old=load(LATEST,{}) or {};oldps=old.get('players',[])
 if len(oldps)<MIN_PLAYERS:print(f'ERRORE: latest.json ha {len(oldps)} giocatori; caricare prima il catalogo completo',file=sys.stderr);return 1
 ps=json.loads(json.dumps(oldps));logs=[];total=0;all_unmatched=[];lineup_votes={}
 for name,url in (cfg.get('sources')or{}).items():
  try:
   raw,ctype=fetch(url);digest=hashlib.sha256(raw).hexdigest();isjson='json'in ctype.lower() or raw.lstrip().startswith((b'{',b'['))
   if isjson:parsed={'records':records_json(json.loads(raw.decode('utf-8-sig'))),'updated_at':None,'kind':'json'}
   else:parsed=parse_source(name,raw.decode('utf-8','replace'))
   if parsed.get('kind')=='lineups':
    for rec in parsed['records']:
     key=(norm(rec.get('name','')),rec.get('club'))
     lineup_votes.setdefault(key,[]).append({'source':name,'starter':float(rec['starter']),'record':rec})
    n=0;miss=[]
   else:
    n,miss=apply(ps,parsed['records'],name);total+=n;all_unmatched += [f'{name}:{x}' for x in miss]
   logs.append({'name':name,'url':url,'status':'extracted' if parsed.get('kind')=='lineups' and parsed['records'] else ('data_applied' if n else 'reachable_no_updates'),'records_extracted':len(parsed['records']),'players_updated':n,'source_updated_at':parsed.get('updated_at'),'sha256':digest})
  except Exception as ex:logs.append({'name':name,'url':url,'status':'error','error':f'{type(ex).__name__}: {ex}'})
 # Applica la titolarità solo con almeno tre fonti indipendenti.
 consensus_updates=0
 for key,votes in lineup_votes.items():
  if len({v['source'] for v in votes})<3:continue
  vals=sorted(v['starter'] for v in votes);median=vals[len(vals)//2]
  kept=[v for v in votes if abs(v['starter']-median)<=35]
  if len({v['source'] for v in kept})<3:continue
  rec=dict(kept[0]['record']);rec['starter']=round(sum(v['starter'] for v in kept)/len(kept),1)
  n,miss=apply(ps,[rec],'lineup_consensus_3_sources');consensus_updates+=n;all_unmatched += [f'consensus:{x}' for x in miss]
 total+=consensus_updates
 logs.append({'name':'lineup_consensus','status':'data_applied' if consensus_updates else 'insufficient_consensus','players_updated':consensus_updates,'minimum_sources':3})
 normalize(ps);errors=validate(ps,len(oldps));stamp=now();roundno=int(cfg.get('round',old.get('round',0)))
 stat={'generated_at':stamp,'round':roundno,'players':len(ps),'player_updates':total,'fresh_player_data':total>0,'sources':logs,'unmatched':all_unmatched[:100],'errors':errors}
 write(STATUS,stat);write(FANTASUITE,{'schema_version':4,'generated_at':stamp,'aggiornamento_riuscito':total>0 and not errors,'dati_precedenti_mantenuti':total==0,'fonti':logs,'errori':errors,'non_associati':all_unmatched[:100]})
 if errors:print('\n'.join(errors),file=sys.stderr);return 1
 result={'schema':'FantaSuite.latest.v6.2','generated_at':stamp,'round':roundno,'players':ps,'recommended_formations':formations(ps),'validation':{'records':len(ps),'critical_errors':[],'player_updates':total,'fresh_player_data':total>0}}
 write(LATEST,result);HISTORY.mkdir(parents=True,exist_ok=True);shutil.copy2(LATEST,HISTORY/f"latest-{stamp.replace(':','-')}.json")
 for x in sorted(HISTORY.glob('latest-*.json'),reverse=True)[30:]:x.unlink(missing_ok=True)
 print(f'OK: {len(ps)} giocatori; {total} aggiornamenti; fonti {len(logs)}');return 0
if __name__=='__main__':raise SystemExit(main())
