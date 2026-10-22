#!/usr/bin/env python3
from __future__ import annotations
import math

def clamp(v,a,b):return max(a,min(b,float(v)))
def expected_minutes(p):
 if p.get('status')=='unavailable':return 0.0
 st=clamp(p.get('starter',0),0,100)/100;ap=clamp(p.get('appearance',0),0,100)/100;prof=p.get('minutes_profile') or {};role=p.get('role','C')
 start=clamp(prof.get('avg_minutes_when_start',{'P':90,'D':82,'C':75,'A':72}.get(role,75)),45,90)
 sub=clamp(prof.get('avg_minutes_when_sub',{'P':8,'D':18,'C':24,'A':27}.get(role,23)),1,45)
 subp=max(0,ap-st)
 return round((st*start+subp*sub)/max(ap,.01),1) if ap>0 else 0.0
def efficiency(p):
 h=p.get('minutes_profile') or {};subs=int(h.get('sub_appearances',0) or 0);starts=int(h.get('starts',0) or 0)
 if subs<8:return 1.0,1.0,'neutral'
 vf=bf=1.0
 if h.get('avg_vote_as_sub') is not None and float(h.get('avg_vote_as_starter',0))>0:vf=clamp(float(h['avg_vote_as_sub'])/float(h['avg_vote_as_starter']),.92,1.08)
 if h.get('bonus_per90_as_sub') is not None and float(h.get('bonus_per90_as_starter',0))>0:bf=clamp(float(h['bonus_per90_as_sub'])/float(h['bonus_per90_as_starter']),.70,1.35)
 return vf,bf,'historical' if starts>=8 else 'sub_sample'
def recalculate_player(p):
 minutes=expected_minutes(p);p['expected_minutes']=minutes
 if p.get('status')=='unavailable':p.update(expected_vote=0.0,expected_fantavote=0.0,efm=0.0,formation_index=0.0);return p
 # Freeze the unadjusted baselines once, so repeated workflows do not compound the minute penalty.
 base_vote=float(p.get('base_expected_vote',p.get('expected_vote',p.get('usual',6.0))))
 base_fv=float(p.get('base_expected_fantavote',p.get('efm',base_vote)))
 p.setdefault('base_expected_vote',round(base_vote,2));p.setdefault('base_expected_fantavote',round(base_fv,2))
 ratio=clamp(minutes/90,0,1);vote_factor=.82+.18*math.sqrt(ratio);bonus_factor=.25+.75*ratio;vf,bf,conf=efficiency(p)
 vote=base_vote*vote_factor*vf;bonus=(base_fv-base_vote)*bonus_factor*bf;fv=vote+bonus;ap=clamp(p.get('appearance',0),0,100)/100
 p.update(expected_vote=round(vote,2),expected_fantavote=round(fv,2),efm=round(fv,2),formation_index=round(fv*(.70+.30*ap),2),minute_model={'vote_factor':round(vote_factor,4),'bonus_factor':round(bonus_factor,4),'individual_vote_factor':round(vf,4),'individual_bonus_factor':round(bf,4),'profile_confidence':conf})
 return p
def recalculate_all(players):
 for p in players:recalculate_player(p)
 return players
