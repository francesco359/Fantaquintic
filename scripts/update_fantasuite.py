import json,hashlib
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.request import Request,urlopen
from statistics import median,mean
R=Path(__file__).resolve().parents[1];D=R/"data";D.mkdir(exist_ok=True);(D/"history").mkdir(exist_ok=True);TZ=ZoneInfo("Europe/Rome")
def ping(u):
 with urlopen(Request(u,headers={"User-Agent":"Mozilla/5.0 FantaSuiteBot/13.4"}),timeout=25) as r:return r.status==200
def recalc(x):
 P=x["players"];rv={r:[] for r in "PDCA"}
 for p in P:
  base=float(p.get("base_vote",6));mins=max(0,min(90,float(p.get("expected_minutes",0))));xg=max(0,float(p.get("xg90",0)));xa=max(0,float(p.get("xa90",0)));ef=0 if p.get("status")=="unavailable" else max(4.5,min(9,base+(mins/90)*(3*xg+xa)));ap=float(p.get("appearance_probability",0));sp=float(p.get("starter_probability",0));risk=float(p.get("injury_risk",.1));rel=max(.15,min(.96,.30+.30*ap+.18*sp+.14*(1-risk)+(.08 if mins>=65 else 0)));p["expected_fantasy_average"]=p["expected_fantasy_average_g8"]=round(ef,2);p["data_reliability"]=round(rel,2);rv[p["role"]].append(ef)
 rm={r:median(v) for r,v in rv.items()}
 for p in P:
  ef=p["expected_fantasy_average"];hist=float(p.get("observed_fantasy_average") or p.get("mean_vote") or p.get("base_vote",6));fv=[float(v) for v in (p.get("form_last5") or [])];form=mean(fv) if fv else hist;dp,dr,df=ef-hist,ef-rm[p["role"]],ef-form;p["deltas"]={"personal":round(dp,2),"role":round(dr,2),"form":round(df,2)};ap=float(p.get("appearance_probability",0));sp=float(p.get("starter_probability",0));rel=float(p.get("data_reliability",.4));st=p.get("status","available");sur=max(0,min(100,50+22*dp+15*dr+10*df+10*(ap-.5)+8*(sp-.5)+6*(rel-.5)));p["surprise_score"]=round(sur,1);ok=st=="available" and ap>=.68 and sp>=.55 and rel>=.55 and sur>=62;p["surprise_eligible"]=ok;p["advice_v134"]="NON SCHIERARE" if st=="unavailable" or ap<.25 else "RISCHIOSO" if st=="doubt" or ap<.55 or float(p.get("expected_minutes",0))<35 else "SORPRESA" if ok else "CONSIGLIATO" if sp>=.70 and ef>=rm[p["role"]]+.15 and rel>=.62 else "SCHIERABILE"
 def xi(key,sur=False):
  z=[]
  for r,n in [("P",1),("D",4),("C",3),("A",3)]:
   a=[p for p in P if p["role"]==r and p.get("status")=="available" and float(p.get("appearance_probability",0))>=.55 and (not sur or p.get("surprise_eligible"))];a.sort(key=lambda p:(float(p.get(key,0)),float(p.get("starter_probability",0))),reverse=True);z+=a[:n]
  return {"m":"433","players":[{"id":p["id"],"name":p["name"],"club":p["club"],"role":p["role"]} for p in z],"expectedSubs":round(sum(1-float(p.get("starter_probability",0)) for p in z),2)}
 x["recommended_formations"]={"best_global_433":xi("expected_fantasy_average"),"surprises_global_433":xi("surprise_score",True)}
def main():
 now=datetime.now(TZ);x=json.loads((D/"latest.json").read_text());ok=[];errors=[];src={"calendar":"https://www.legaseriea.it/serie-a/calendario-risultati","injuries":"https://www.sosfanta.com/indisponibili-e-squalificati/tabella-indisponibili-seriea-fantacalcio-asta-infortunati-tempi-recupero-squalificati-diffidati/","lineups":"https://www.fantacalcio-online.com/it/serie-a/2026-2027/probabili-formazioni/ultima-giornata"}
 for k,u in src.items():
  try:
   if ping(u):ok.append(k)
  except Exception as e:errors.append(k+": "+str(e))
 recalc(x);x["generated_at"]=now.isoformat();raw=json.dumps(x,ensure_ascii=False,indent=2);v=now.strftime("%Y.%m.%d.%H%M");(D/"history"/f"{v}.json").write_text(raw);(D/"latest.json").write_text(raw);st={"version":v,"generated_at":now.isoformat(),"round":x.get("round"),"players":len(x["players"]),"update_mode":"automatic","sources_ok":ok,"errors":errors,"lineups_frozen":False,"checksum":hashlib.sha256(raw.encode()).hexdigest()};(D/"status.json").write_text(json.dumps(st,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
