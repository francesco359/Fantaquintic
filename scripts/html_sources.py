#!/usr/bin/env python3
from __future__ import annotations
import re, unicodedata
from datetime import datetime
from typing import Any
from bs4 import BeautifulSoup

TEAM_MAP={'atalanta':'ATA','bologna':'BOL','cagliari':'CAG','como':'COM','fiorentina':'FIO','frosinone':'FRO','genoa':'GEN','inter':'INT','juventus':'JUV','lazio':'LAZ','lecce':'LEC','milan':'MIL','monza':'MON','napoli':'NAP','parma':'PAR','roma':'ROM','sassuolo':'SAS','torino':'TOR','udinese':'UDI','venezia':'VEN'}
TEAM_ALIASES={'ata':'ATA','bol':'BOL','cag':'CAG','com':'COM','fio':'FIO','fro':'FRO','gen':'GEN','int':'INT','juv':'JUV','laz':'LAZ','lec':'LEC','mil':'MIL','mon':'MON','nap':'NAP','par':'PAR','rom':'ROM','sas':'SAS','tor':'TOR','udi':'UDI','ven':'VEN'}
ROLE_WORDS={'p','d','c','a','portiere','difensore','centrocampista','attaccante'}
NOISE=re.compile(r'\b(mercato|vittoria|quote|pronostico|cookie|newsletter|giornata|campionato|pubblicità|formazioni|titolari|panchina|ballottaggi|indisponibili)\b',re.I)
PCT=re.compile(r'^(100|[1-9]?\d(?:[.,]\d)?)\s*%$')

def clean(x):return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',str(x or '')).replace('\xa0',' ')).strip()
def norm(x):
 x=clean(x).casefold().replace('ø','o').replace('đ','d')
 x=''.join(c for c in unicodedata.normalize('NFD',x) if unicodedata.category(c)!='Mn')
 return re.sub(r'[^a-z0-9]+',' ',x).strip()
def page(html):
 s=BeautifulSoup(html,'html.parser')
 for t in s(['script','style','noscript','svg','iframe']):t.decompose()
 return s
def valid_name(x):
 x=clean(x);w=x.split()
 return 1<=len(w)<=5 and 2<=len(x)<=48 and not NOISE.search(x) and bool(re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ.'’\- ]+",x))
def updated(text):
 m=re.search(r'(?:Ultimo aggiornamento|Aggiornato(?: il)?|Ultima rilevazione:|Al)\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{1,2}\s+[a-zà]+\s+\d{4})(?:\s*(?:[-–,]|alle|ore)\s*(\d{1,2}:\d{2}))?',text,re.I)
 if not m:return None
 return clean(' '.join(x for x in m.groups() if x))
def club_from_text(x):
 n=norm(x)
 if n in TEAM_MAP:return TEAM_MAP[n]
 if n in TEAM_ALIASES:return TEAM_ALIASES[n]
 return None
def rec(name,club,pct,source):return {'name':clean(name),'club':club,'starter':round(float(str(pct).replace(',','.')),1),'status':'available','source':source}
def dedupe(records):
 out={}
 for x in records:
  if x.get('club') and valid_name(x.get('name','')):out[(norm(x['name']),x['club'])]=x
 return list(out.values())

def parse_fantacalcio(s,source):
 out=[];href=re.compile(r'/serie-a/squadre/([^/]+)/[^/]+/\d+',re.I)
 for a in s.find_all('a',href=True):
  m=href.search(a.get('href',''));name=clean(a.get_text(' ',strip=True))
  if not m or not valid_name(name):continue
  club=club_from_text(m.group(1));value=None;seen=0
  for node in a.next_elements:
   if node is not a and getattr(node,'name',None)=='a':break
   if isinstance(node,str):
    z=clean(node)
    if not z:continue
    seen+=1;q=PCT.match(z)
    if q:value=q.group(1);break
    if seen>7:break
  if value is None and a.parent:
   q=re.search(r'(100|[1-9]?\d(?:[.,]\d)?)\s*%',clean(a.parent.get_text(' ',strip=True)))
   if q:value=q.group(1)
  if club and value is not None:out.append(rec(name,club,value,source))
 return dedupe(out)

def parse_percent_name_lines(s,source):
 # SOS/FantaMaster: percentuale e nome possono essere nello stesso nodo o in nodi consecutivi.
 lines=[clean(x) for x in s.stripped_strings if clean(x)];out=[];club=None
 for i,line in enumerate(lines):
  c=club_from_text(line)
  if c:club=c;continue
  if not club:continue
  m=re.match(r'^(100|[1-9]?\d(?:[.,]\d)?)\s*%\s*(?:[PDCA]\s+)?(.+)$',line,re.I)
  if m and valid_name(m.group(2)):out.append(rec(m.group(2),club,m.group(1),source));continue
  m=re.match(r'^(?:[PDCA]\s+)?(.+?)\s+(100|[1-9]?\d(?:[.,]\d)?)\s*%$',line,re.I)
  if m and valid_name(m.group(1)):out.append(rec(m.group(1),club,m.group(2),source));continue
  if PCT.match(line) and i+1<len(lines):
   name=re.sub(r'^[PDCA]\s+','',lines[i+1],flags=re.I)
   if valid_name(name):out.append(rec(name,club,PCT.match(line).group(1),source))
  elif valid_name(re.sub(r'^[PDCA]\s+','',line,flags=re.I)) and i+1<len(lines) and PCT.match(lines[i+1]):
   name=re.sub(r'^[PDCA]\s+','',line,flags=re.I);out.append(rec(name,club,PCT.match(lines[i+1]).group(1),source))
 return dedupe(out)

def parse_consensus_table(s,source):
 # Fantacalcio-Online: usa la colonna Media*, non conta come tre fonti separate.
 text='\n'.join(clean(x) for x in s.stripped_strings if clean(x));out=[];club=None
 for line in text.splitlines():
  c=club_from_text(line)
  if c:club=c;continue
  if not club:continue
  # ruolo + nome + 3/4 percentuali + media finale
  m=re.match(r'^[PDCA]\s+(.+?)\s+((?:\d{1,3}%|[–-])(?:\s+(?:\d{1,3}%|[–-])){2,5})$',line,re.I)
  if not m:continue
  name=clean(m.group(1));vals=[int(x) for x in re.findall(r'(\d{1,3})%',m.group(2))]
  if valid_name(name) and vals:out.append(rec(name,club,vals[-1],source))
 return dedupe(out)

def parse_lineups(html,source='lineups'):
 s=page(html);low=source.casefold();text='\n'.join(clean(x) for x in s.stripped_strings if clean(x))
 if 'fantacalcio' in low and 'consensus' not in low:records=parse_fantacalcio(s,source)
 elif 'consensus' in low:records=parse_consensus_table(s,source)
 else:records=parse_percent_name_lines(s,source)
 return {'records':records,'updated_at':updated(text),'kind':'lineups'}
def parse_availability(html,source='injuries'):
 s=page(html);lines=[clean(x) for x in s.stripped_strings if clean(x)];out=[];club=None;section=None
 for line in lines:
  c=club_from_text(line)
  if c:club=c;section=None;continue
  low=norm(line)
  if low.startswith('infortunati'):section='injury';continue
  if low.startswith('squalificati'):section='suspension';continue
  if low.startswith('in dubbio'):section='doubt';continue
  if not club or not section:continue
  m=re.match(r"^([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ.'’\- ]{1,34}?)(?:\s+-\s+|\s{2,})(.+)$",line)
  if not m:continue
  name,reason=clean(m.group(1)),clean(m.group(2));status='doubt' if section=='doubt' or re.search(r'in dubbio|da valutare|recuperabile',reason,re.I) else 'unavailable'
  if valid_name(name):
   x={'name':name,'club':club,'status':status,'reason':reason,'availability_type':section,'source':source}
   if status=='unavailable':x.update(starter=0.0,appearance=0.0)
   out.append(x)
 return {'records':dedupe(out),'updated_at':updated('\n'.join(lines)),'kind':'availability'}
def parse_source(name,html):
 low=name.casefold()
 if 'lineup' in low or 'formazion' in low:return parse_lineups(html,name)
 if any(x in low for x in ('injur','infortun','indispon','squal')):return parse_availability(html,name)
 return {'records':[],'updated_at':None,'kind':'unsupported'}
