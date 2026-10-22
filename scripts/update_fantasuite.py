#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,os,re,shutil,sys,tempfile,unicodedata,urllib.request
from datetime import datetime,timezone
from pathlib import Path
from html_sources import parse_source
from expectation_model import recalculate_all
ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'data';HISTORY=DATA/'history';LATEST=DATA/'latest.json';STATUS=DATA/'status.json';FANTASUITE=DATA/'fantasuite.json';CONFIG=ROOT/'config.json';ALIASES=DATA/'player_aliases.json';MINUTE_PROFILES=DATA/'player_minutes_profiles.json'
MIN_PLAYERS=int(os.getenv('FANTASUITE_MIN_PLAYERS','490'));VALID={'available','doubt','unavailable'}
def now():return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
def load(p,d=None):
 try:return json.loads(p.read_text(encoding='utf-8'))
 except Exception:return d
def write(p,x):
 p.parent.mkdir(parents=True,exist_ok=True);t=json.dumps(x,ensure_ascii=False,indent=2)+'\n'
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=p.parent,delete=False) as f:f.write(t);n=Path(f.name)
 n.replace(p)
def fetch(url):
 q=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 FantaQuintoc/6.4','Accept':'text/html,application/json'})
 with urllib.request.urlopen(q,timeout=35) as r:return r.read(),r.headers.get('Content-Type','')
def norm(s):
 s=str(s or '').casefold().replace('ø','o');s=''.join(c for c in unicodedata.normalize('NFD',s) if unicodedata.category(c)!='Mn')
 return re.sub(r'[^a-z0-9]+',' ',s).strip()
def variants(s):
 p=norm(s).split();out={' '.join(p)}
 if len(p)>1:out|={p[0],p[-1],' '.join(reversed(p))}
 return {x for x in out if len(x)>1}
def indexes(players):
 ids={int(p['id']):p for p in players};names={};alias_meta={}
 for p in players:
  for k in variants(p['name']):names.setdefault(k,[]).append(p)
 doc=load(ALIASES,{})or{}
 for item in doc.get('players',[]):
  try:pid=int(item['id']);p=ids[pid]
  except (KeyError,TypeError,ValueError):continue
  # Tutti gli alias possono essere usati con conferma di squadra/ruolo.
  for alias in item.get('aliases',[]):names.setdefault(norm(alias),[]).append(p)
  # Solo gli alias globalmente univoci sono ammessi come fallback senza squadra.
  for alias in item.get('unique_aliases',[]):alias_meta.setdefault(norm(alias),set()).add(pid)
 # deduplica le liste create da alias equivalenti
 for k,v in names.items():names[k]=list({int(p['id']):p for p in v}.values())
 return ids,names,alias_meta
def resolve(r,ids,names,alias_meta=None):
 try:
  rid=int(r.get('id'))
  if rid in ids:return ids[rid]
 except (TypeError,ValueError):pass
 alias_meta=alias_meta or {};found=[]
 for k in variants(r.get('name','')):found+=names.get(k,[])
 candidates=list({int(p['id']):p for p in found}.values())
 role=r.get('role');source_club=r.get('club')
 if role:candidates=[p for p in candidates if p.get('role')==role]
 same=[p for p in candidates if source_club and p.get('club')==source_club]
 if len(same)==1:return same[0]
 # Fallback soltanto se un alias del record è globalmente univoco.
 unique_ids=set()
 for k in variants(r.get('name','')):unique_ids |= alias_meta.get(k,set())
 unique=[p for p in candidates if int(p['id']) in unique_ids]
 if len(unique)==1:return unique[0]
 if not source_club and len(candidates)==1:return candidates[0]
 return None
def apply(ps,records,source):
 ids,names,alias_meta=indexes(ps);n=0;miss=[]
 allowed={'efm','starter','appearance','status','usual','surprise','hidden','reliability','matchup','coach','coachScore','surpriseEligible','reason','availability_type','expected_return'}
 for r in records:
  p=resolve(r,ids,names,alias_meta)
  if not p:miss.append(r.get('name',r.get('id')));continue
  changed=False
  for k in allowed:
   if k in r:p[k]=r[k];changed=True
  if changed:p['updated_by']=source;p['updated_at']=now();n+=1
 return n,miss
def normalize(ps):
 for p in ps:
  p['id']=int(p['id']);p['efm']=round(float(p.get('efm',0)),2);p['starter']=round(max(0,min(100,float(p.get('starter',0)))),1);p['appearance']=round(max(0,min(100,float(p.get('appearance',0)))),1)
  if p.get('status')=='unavailable':p['starter']=p['appearance']=0.0
  elif p['appearance']<p['starter']:p['appearance']=p['starter']
  if 'usual'in p:p['usual']=round(float(p['usual']),2);p['delta']=round(p['efm']-p['usual'],2)
def validate(ps,oldn):
 e=[]
 if len(ps)<MIN_PLAYERS:e.append(f'catalogo incompleto {len(ps)}')
 if len(ps)<oldn:e.append('regressione catalogo')
 ids=set()
 for p in ps:
  if p['id'] in ids:e.append(f"ID duplicato {p['id']}")
  ids.add(p['id'])
  if not 0<=p['starter']<=p['appearance']<=100:e.append(f"probabilità {p['id']}")
  if p.get('status')=='unavailable' and (p['starter']or p['appearance']):e.append(f"indisponibile {p['id']}")
 return e
def formations(ps):
 out=[]
 for r,c in {'P':1,'D':4,'C':3,'A':3}.items():
  q=sorted((p for p in ps if p.get('role')==r and p.get('status')!='unavailable' and p.get('appearance',0)>0),key=lambda p:(p.get('formation_index',p['efm']),p['appearance']),reverse=True)[:c]
  out += [{'id':p['id'],'name':p['name'],'role':r} for p in q]
 return {'best_global_433':{'module':'4-3-3','players':out}}
def main():
 cfg=load(CONFIG,{})or{};old=load(LATEST,{})or{};oldps=old.get('players',[])
 if len(oldps)<MIN_PLAYERS:print('latest.json incompleto',file=sys.stderr);return 1
 ps=json.loads(json.dumps(oldps));logs=[];total=0;miss=[];votes={};single_evidence=[]
 ids,names,alias_meta=indexes(ps)
 for name,url in (cfg.get('sources')or{}).items():
  try:
   raw,ctype=fetch(url);parsed=parse_source(name,raw.decode('utf-8','replace'))
   if parsed.get('kind')=='lineups':
    resolved=0;source_unmatched=[]
    for r in parsed['records']:
     player=resolve(r,ids,names,alias_meta)
     if not player:
      source_unmatched.append(r.get('name'));continue
     # Raggruppamento canonico per ID, non per testo del nome.
     canonical=dict(r);canonical['id']=int(player['id']);canonical['name']=player['name'];canonical['club']=player['club'];canonical['role']=player.get('role')
     votes.setdefault(int(player['id']),[]).append((name,float(r['starter']),canonical))
     resolved+=1
    n=0;miss += [f'{name}:{x}' for x in source_unmatched];status='extracted' if parsed['records'] else 'reachable_no_updates'
    logs.append({'name':name,'url':url,'status':status,'records_extracted':len(parsed['records']),'records_resolved':resolved,'players_updated':0,'source_updated_at':parsed.get('updated_at'),'sha256':hashlib.sha256(raw).hexdigest()})
   else:
    n,m=apply(ps,parsed['records'],name);total+=n;miss += [f'{name}:{x}' for x in m];status='data_applied' if n else 'reachable_no_updates'
    logs.append({'name':name,'url':url,'status':status,'records_extracted':len(parsed['records']),'players_updated':n,'source_updated_at':parsed.get('updated_at'),'sha256':hashlib.sha256(raw).hexdigest()})
  except Exception as ex:logs.append({'name':name,'url':url,'status':'error','error':f'{type(ex).__name__}: {ex}'})
 consensus=0;details=[];blocked=[]
 for pid,rows in votes.items():
  rows=list({x[0]:x for x in rows}.values());player=ids[pid];vals=[x[1] for x in rows]
  if len(rows)>=2:
   spread=max(vals)-min(vals)
   if spread>30:
    blocked.append({'id':pid,'name':player['name'],'reason':'spread_exceeded','spread':spread,'sources':{x[0]:x[1] for x in rows}});continue
   final=sorted(vals)[len(vals)//2] if len(vals)>=3 else round(sum(vals)/2,1)
   confidence='high' if len(rows)>=3 else 'medium';rule='consensus'
  else:
   # Una sola fonte non può promuovere un calciatore a titolare.
   # Può soltanto correggere un vecchio dato alto se lo colloca esplicitamente in panchina (<=45%).
   fresh=vals[0];previous=float(player.get('starter',0))
   if fresh<=49 and previous-fresh>=20:
    final=fresh;confidence='low';rule='single_source_bench_downgrade'
    single_evidence.append({'id':pid,'name':player['name'],'previous':previous,'starter':final,'source':rows[0][0]})
   else:
    blocked.append({'id':pid,'name':player['name'],'reason':'only_one_source','previous':previous,'sources':{rows[0][0]:fresh}});continue
  r=dict(rows[0][2]);r['starter']=round(final,1)
  if r['starter']<=49:r['appearance']=min(float(player.get('appearance',100)),r['starter']+35)
  n,m=apply(ps,[r],f'lineup_{rule}');consensus+=n;miss += [f'consensus:{x}' for x in m]
  if n:details.append({'id':pid,'name':player['name'],'club':player.get('club'),'starter':r['starter'],'previous_starter':player.get('starter'),'confidence':confidence,'rule':rule,'sources':{x[0]:x[1] for x in rows}})
 total+=consensus
 logs.append({'name':'lineup_consensus','status':'data_applied' if consensus else 'insufficient_consensus','players_updated':consensus,'configured_sources':3,'minimum_sources':2,'maximum_spread':30,'single_source_bench_updates':len(single_evidence),'sample':details[:40],'blocked_sample':blocked[:40]})
 profiles=(load(MINUTE_PROFILES,{})or{}).get('profiles',{})
 for p in ps:
  prof=profiles.get(str(p['id']))
  if isinstance(prof,dict):p['minutes_profile']=prof
 recalculate_all(ps)
 normalize(ps);errors=validate(ps,len(oldps));stamp=now();rnd=int(cfg.get('round',old.get('round',0)))
 stat={'generated_at':stamp,'round':rnd,'players':len(ps),'player_updates':total,'fresh_player_data':total>0,'sources':logs,'unmatched':miss[:150],'errors':errors}
 write(STATUS,stat);write(FANTASUITE,{'schema_version':7,'generated_at':stamp,'aggiornamento_riuscito':total>0 and not errors,'dati_precedenti_mantenuti':total==0,'fonti':logs,'errori':errors,'non_associati':miss[:150]})
 if errors:return 1
 result={'schema':'FantaSuite.latest.v6.8','generated_at':stamp,'round':rnd,'players':ps,'recommended_formations':formations(ps),'validation':{'records':len(ps),'critical_errors':[],'player_updates':total,'fresh_player_data':total>0,'canonical_lineup_matching':True}}
 write(LATEST,result);HISTORY.mkdir(parents=True,exist_ok=True);shutil.copy2(LATEST,HISTORY/f"latest-{stamp.replace(':','-')}.json")
 print(f'OK {len(ps)} giocatori, {total} aggiornamenti, {len(single_evidence)} correzioni panchina da fonte singola');return 0
if __name__=='__main__':raise SystemExit(main())
