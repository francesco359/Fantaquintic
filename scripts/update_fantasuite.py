#!/usr/bin/env python3
from __future__ import annotations
import json, tempfile
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data'; SOURCE=DATA/'FantaSuite_stato_G8.json'
def write(path,obj):
 path.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=path.parent,delete=False) as f: json.dump(obj,f,ensure_ascii=False,indent=2);f.write('\n');tmp=Path(f.name)
 tmp.replace(path)
def fm(p,specific):
 if p.get('status')=='unavailable': return 0.0
 m=float(p.get('expected_minutes',0));v=float(p.get('base_vote',6))+(3*float(p.get('xg90',0))+float(p.get('xa90',0)))*m/90+(float(specific.get(p['name'],1))-1)*.18
 if p.get('status')=='doubt':v-=.10
 return round(max(0,v),2)
def main():
 state=json.loads(SOURCE.read_text(encoding='utf-8')); ps=state.get('players',[])
 if len(ps)!=502 or len({p['id'] for p in ps})!=502: raise SystemExit('Dataset sorgente non valido: servono 502 ID univoci')
 old={}
 try: old={p['id']:p for p in json.loads((DATA/'latest.json').read_text(encoding='utf-8')).get('players',[])}
 except Exception: pass
 spec=state.get('tactical',{}).get('specific',{});out=[]
 for p in ps:
  e=fm(p,spec);prev=old.get(p['id'],{});q={**p,'team':prev.get('team','Svincolati'),'efm':e,'expected_fantasy_average':e,'expected_vote':round(float(p.get('base_vote',6)),2),'starter':round(float(p.get('starter_probability',0))*100,1),'appearance':round(float(p.get('appearance_probability',0))*100,1),'advice_v135':'INDISPONIBILE' if p.get('status')=='unavailable' else 'DA VALUTARE' if p.get('status')=='doubt' else 'DISPONIBILE','data_reliability':round(.45+.35*float(p.get('appearance_probability',0))+.2*(1-float(p.get('injury_risk',0))),3),'surprise_score':prev.get('surprise_score',50),'deltas':{'personal':round(e-float(p.get('observed_fantasy_average',e)),2),'role':0,'form':0},'malus_risk':prev.get('malus_risk',0),'coach_trust':{'score':round(float(p.get('starter_probability',0))*100)},'opponent_coach_impact':{'score':0}};out.append(q)
 form=[]
 for r,n in [('P',1),('D',4),('C',3),('A',3)]:
  ok=sorted((p for p in out if p['role']==r and p['status']!='unavailable' and p.get('appearance_probability',0)>0),key=lambda x:(x['efm'],x.get('appearance_probability',0)),reverse=True)[:n];form += [{'id':p['id'],'name':p['name'],'role':r} for p in ok]
 now=datetime.now(timezone.utc).isoformat(); latest={'schema':'FantaSuite.latest.v14.6','generated_at':now,'round':state.get('round',8),'players':out,'recommended_formations':{'best_global_433':{'module':'4-3-3','players':form},'surprises_global_433':{'module':'4-3-3','players':form}}}
 old_text=(DATA/'latest.json').read_text(encoding='utf-8') if (DATA/'latest.json').exists() else ''; new_core=json.dumps({**latest,'generated_at':None},ensure_ascii=False,sort_keys=True);old_core=''
 try: old_core=json.dumps({**json.loads(old_text),'generated_at':None},ensure_ascii=False,sort_keys=True)
 except Exception: pass
 changed=new_core!=old_core; status={'schema':'FantaSuite.status.v14.6','generated_at':now,'round':state.get('round',8),'players':502,'changed':changed,'sources_ok':['FantaSuite_stato_G8.json','motore unificato v14.6'],'errors':[]}
 write(DATA/'latest.json',latest);write(DATA/'status.json',status);write(DATA/'history'/('latest-'+now.replace(':','-')+'.json'),latest)
 hist=sorted((DATA/'history').glob('latest-*.json'),reverse=True)
 for p in hist[30:]:p.unlink(missing_ok=True)
 print('Aggiornamento completato:',len(out),'giocatori; modifiche:',changed)
if __name__=='__main__':main()
