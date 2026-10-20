import json,re,hashlib,sys
from pathlib import Path
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from urllib.request import Request,urlopen
from statistics import median
R=Path(__file__).resolve().parents[1];C=json.loads((R/'config.json').read_text());D=R/'data';TZ=ZoneInfo(C['timezone']);D.mkdir(exist_ok=True);(D/'history').mkdir(exist_ok=True)
def fetch(u,json_mode=False):
 with urlopen(Request(u,headers={'User-Agent':'Mozilla/5.0 FantaSuiteBot/13.3','Accept-Language':'it-IT'}),timeout=30) as r:s=r.read().decode('utf-8','replace')
 return json.loads(s) if json_mode else re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',s))
def sync_round(x):
 try: rows=fetch(C['sources']['calendar_json'],True)
 except Exception as e:x.setdefault('automation',{}).setdefault('errors',[]).append('calendar: '+str(e));return []
 now=datetime.now(TZ);games=[]
 for z in rows:
  rnd=int(z.get('Round Number') or z.get('Round') or 0);raw=z.get('DateUtc') or z.get('Date') or z.get('date');
  try:k=datetime.fromisoformat(str(raw).replace('Z','+00:00')).astimezone(TZ)
  except:continue
  games.append({'round':rnd,'home':z.get('Home Team') or z.get('HomeTeam'),'away':z.get('Away Team') or z.get('AwayTeam'),'kickoff':k.isoformat(),'result':z.get('Result')})
 future=[g for g in games if datetime.fromisoformat(g['kickoff'])+timedelta(hours=2,minutes=15)>now];target=min((g['round'] for g in future),default=x.get('round',1));x['round']=target;x['fixtures']=[g for g in games if g['round']==target];return x['fixtures']
def enrich(x):
 P=x['players'];rm={r:median([float(p.get('expected_fantasy_average_g8',p.get('expected_fantasy_average',p.get('fm',p.get('base',6)))) or 0) for p in P if p.get('role')==r]) for r in 'PDCA'}
 for p in P:
  ex=float(p.get('expected_fantasy_average_g8',p.get('expected_fantasy_average',p.get('fm',p.get('base',6)))) or 0);hist=float(p.get('observed_fantasy_average',p.get('fm',p.get('base',6))) or 6);f=p.get('form_last5') or [];form=median([float(v) for v in f]) if f else hist; p['deltas']={'personal':round(ex-hist,2),'role':round(ex-rm.get(p.get('role'),6),2),'form':round(ex-form,2)};ap=float(p.get('appearance_probability',0));sp=float(p.get('starter_probability',0));st=p.get('status','available');p['advice_v133']='NON CONSIGLIATO' if st=='unavailable' or ap<.35 else 'RISCHIOSO' if st=='doubt' or ap<.58 else 'CONSIGLIATO' if sp>=.75 and ex>=rm.get(p.get('role'),6) else 'SCHIERABILE'
 def make(key,sur=False):
  q=[p for p in P if p.get('status')=='available' and float(p.get('appearance_probability',0))>=.55];s=[]
  for r,n in [('P',1),('D',4),('C',3),('A',3)]:
   a=[p for p in q if p.get('role')==r and (not sur or p.get('surprise_eligible',True))];a.sort(key=lambda p:(float(p.get(key,0) or 0),float(p.get('starter_probability',0))),reverse=True);s+=a[:n]
  return {'m':'433','players':[{'id':p['id'],'name':p['name'],'role':p['role'],'club':p.get('club')} for p in s],'expectedSubs':round(sum(1-float(p.get('starter_probability',0)) for p in s),2)}
 x['recommended_formations']={'best_global_433':make('expected_fantasy_average_g8'),'surprises_global_433':make('surprise_score',True)}
def main(force=False):
 x=json.loads((D/'latest.json').read_text());now=datetime.now(TZ);fs=sync_round(x);live=any(datetime.fromisoformat(g['kickoff'])<=now<=datetime.fromisoformat(g['kickoff'])+timedelta(hours=2,minutes=15) for g in fs);errors=x.setdefault('automation',{}).setdefault('errors',[])
 for source in ('injuries_sos','injuries_sky'):
  try:fetch(C['sources'][source])
  except Exception as e:errors.append(source+': '+str(e))
 if not live:
  try:fetch(C['sources']['lineups'])
  except Exception as e:errors.append('lineups: '+str(e))
 enrich(x);x['generated_at']=now.isoformat();x['update_mode']='live' if live else 'automatic';x['automation']['lineups_frozen']=live;raw=json.dumps(x,ensure_ascii=False,indent=2);v=now.strftime('%Y.%m.%d.%H%M');(D/'history'/f'{v}.json').write_text(raw);(D/'latest.json').write_text(raw);(D/'status.json').write_text(json.dumps({'version':v,'generated_at':now.isoformat(),'round':x['round'],'players':len(x['players']),'checksum':hashlib.sha256(raw.encode()).hexdigest(),'errors':errors},ensure_ascii=False,indent=2))
if __name__=='__main__':main('--force' in sys.argv)
