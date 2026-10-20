import json,re,hashlib,sys
from pathlib import Path
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from urllib.request import Request,urlopen
R=Path(__file__).resolve().parents[1]; C=json.loads((R/'config.json').read_text()); D=R/'data'; TZ=ZoneInfo(C['timezone'])
def get(u):
 with urlopen(Request(u,headers={'User-Agent':'Mozilla/5.0 FantaSuiteBot/13.2','Accept-Language':'it-IT'}),timeout=25) as r:return re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',r.read().decode('utf-8','replace')))
def fixtures():return sorted([datetime.fromisoformat(x['kickoff']).astimezone(TZ) for x in C['fixtures']])
def phase(t):
 f=fixtures();live=any(k<=t<=k+timedelta(hours=2,minutes=15) for k in f)
 return 'live' if live else 'pre_match' if f[0]-timedelta(hours=3)<=t<f[0] else 'post_round' if t>f[-1]+timedelta(hours=2,minutes=15) else 'normal'
def due(t,last,ph):
 gap=timedelta(minutes=30) if ph=='pre_match' else timedelta(hours=6 if t.weekday()<4 else 3 if t.weekday()==4 else 1)
 return not last or t-last>=gap
def apply_med(txt,payload,src):
 changed=0
 for p in payload['players']:
  hits=[s for s in re.split(r'(?<=[.!?])\s+',txt) if p['name'].lower() in s.lower() and any(w in s.lower() for w in ['infortun','lesion','frattur','risentiment','dubbio'])]
  if not hits:continue
  s=hits[0];bad=any(w in s.lower() for w in ['fuori','stop','indisponibile','lesione','frattura']);p['status']='unavailable' if bad else 'doubt';p['note']=s[:420]
  if bad:
   for k in ['appearance_probability','starter_probability','vote_probability','expected_minutes','expected_fantasy_average_g8','surprise_score','hidden_value']:p[k]=0
  p['surprise_eligible']=False;changed+=1
 return changed
def lineups(txt,payload):
 n=0
 for p in payload['players']:
  z=re.search(re.escape(p['name'])+r'.{0,180}?(\d{1,3})%',txt,re.I)
  if z and p.get('status')=='available':q=min(1,int(z.group(1))/100);p['starter_probability']=q;p['appearance_probability']=min(.99,q+.04);p['expected_minutes']=round(38+48*q);n+=1
 return n
def main(force=False):
 t=datetime.now(TZ);latest=D/'latest.json';status=D/'status.json';x=json.loads(latest.read_text());st=json.loads(status.read_text()) if status.exists() else {};last=datetime.fromisoformat(st['generated_at']).astimezone(TZ) if st.get('generated_at') else None;ph=phase(t)
 if not force and not due(t,last,ph):print('SKIP');return
 errors=[];counts={};sources=[]
 for k in ['injuries_sos','injuries_sky']:
  try:counts[k]=apply_med(get(C['sources'][k]),x,k);sources.append({'id':k,'name':k,'updated_at':t.isoformat()})
  except Exception as e:errors.append(k+': '+str(e))
 if ph not in ('live','post_round'):
  try:counts['lineups']=lineups(get(C['sources']['lineups']),x)
  except Exception as e:errors.append('lineups: '+str(e))
 if ph=='post_round':
  try:(D/'votes_snapshot.txt').write_text(get(C['sources']['votes']),encoding='utf-8')
  except Exception as e:errors.append('votes: '+str(e))
 x.update(schema='FantaSuite.full-update.v1',generated_at=t.isoformat(),update_mode=ph,sources=sources,automation={'counts':counts,'errors':errors,'lineups_frozen':ph=='live'})
 raw=json.dumps(x,ensure_ascii=False,indent=2);v=t.strftime('%Y.%m.%d.%H%M');(D/'history'/f'{v}.json').write_text(raw,encoding='utf-8');latest.write_text(raw,encoding='utf-8');status.write_text(json.dumps({'version':v,'generated_at':t.isoformat(),'round':x.get('round'),'players':len(x['players']),'update_mode':ph,'lineups_frozen':ph=='live','checksum':hashlib.sha256(raw.encode()).hexdigest(),'errors':errors},ensure_ascii=False,indent=2));print(v,ph,counts,errors)
if __name__=='__main__':main('--force' in sys.argv)
