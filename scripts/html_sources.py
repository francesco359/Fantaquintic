#!/usr/bin/env python3
from __future__ import annotations
import re, unicodedata
from datetime import datetime
from bs4 import BeautifulSoup
TEAM_MAP={'atalanta':'ATA','bologna':'BOL','cagliari':'CAG','como':'COM','fiorentina':'FIO','frosinone':'FRO','genoa':'GEN','inter':'INT','juventus':'JUV','lazio':'LAZ','lecce':'LEC','milan':'MIL','monza':'MON','napoli':'NAP','parma':'PAR','roma':'ROM','sassuolo':'SAS','torino':'TOR','udinese':'UDI','venezia':'VEN'}
PCT=re.compile(r'^(100|[1-9]?\d(?:[.,]\d)?)\s*%$')
def clean(x):return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',str(x or '')).replace('\xa0',' ')).strip()
def norm(x):
 x=clean(x).casefold().replace('ø','o');x=''.join(c for c in unicodedata.normalize('NFD',x) if unicodedata.category(c)!='Mn')
 return re.sub(r'[^a-z0-9]+',' ',x).strip()
def soup(html):
 s=BeautifulSoup(html,'html.parser')
 for t in s(['script','style','noscript','svg','iframe']):t.decompose()
 return s
def club(x):return TEAM_MAP.get(norm(x))
def valid_name(x):return 2<=len(clean(x))<=48 and 1<=len(clean(x).split())<=5 and bool(re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ.'’\- ]+",clean(x)))
def stamp(text):
 m=re.search(r'(?:Ultimo aggiornamento|Aggiornato(?: il)?|Al)\s*(\d{1,2}/\d{1,2}/\d{4})(?:\s*[-–]\s*(\d{1,2}:\d{2}))?',text,re.I)
 return ' '.join(x for x in m.groups() if x) if m else None
def dedupe(xs):
 d={}
 for x in xs:
  if x.get('club') and valid_name(x.get('name')):d[(norm(x['name']),x['club'])]=x
 return list(d.values())
def R(name,c,pct,source,**extra):
 value=float(str(pct).replace(',','.'))
 return {'name':clean(name),'club':c,'starter':value,'lineup_context':'bench' if value<=49 else ('ballot' if value<75 else 'starter'),'status':'available','source':source,**extra}

def parse_fantacalcio(s,source):
 out=[];h=re.compile(r'/serie-a/squadre/([^/]+)/[^/]+/\d+',re.I)
 for a in s.find_all('a',href=True):
  m=h.search(a.get('href',''));name=clean(a.get_text(' ',strip=True))
  if not m or not valid_name(name):continue
  c=club(m.group(1));pct=None;count=0
  for n in a.next_elements:
   if n is not a and getattr(n,'name',None)=='a':break
   if isinstance(n,str):
    z=clean(n)
    if not z:continue
    count+=1;q=PCT.match(z)
    if q:pct=q.group(1);break
    if count>7:break
  if c and pct is not None:out.append(R(name,c,pct,source))
 return dedupe(out)

def parse_sos(s,source):
 lines=[clean(x) for x in s.stripped_strings if clean(x)];out=[];c=None
 for i,line in enumerate(lines):
  tc=club(line)
  if tc:c=tc;continue
  if not c:continue
  m=re.match(r'^(100|[1-9]?\d(?:[.,]\d)?)%\s*(.+)$',line)
  if m and valid_name(m.group(2)):out.append(R(m.group(2),c,m.group(1),source));continue
  if PCT.match(line) and i+1<len(lines) and valid_name(lines[i+1]):out.append(R(lines[i+1],c,PCT.match(line).group(1),source))
 return dedupe(out)

def parse_gazzetta(s,source):
 out=[];current=None;mode='starter'
 # In actual page club links precede their formation blocks.
 for node in s.descendants:
  if getattr(node,'name',None)=='a':
   m=re.search(r'/calcio/squadre/([^/]+)/?',node.get('href',''),re.I)
   if m and club(m.group(1)):current=club(m.group(1));mode='starter';continue
  if not isinstance(node,str) or not current:continue
  line=clean(node);low=norm(line)
  if low.startswith('panchina'):mode='bench';continue
  if low.startswith(('ballottaggio','squalificati','indisponibili','diffidati','altri')):continue
  m=re.match(r'^(.+?)\s+\d{1,2}$',line) or re.match(r'^\d{1,2}\s+(.+)$',line)
  if m and valid_name(m.group(1)):out.append(R(m.group(1),current,90 if mode=='starter' else 30,source,inferred=True))
 return dedupe(out)

def parse_injury_table(s,source):
 out=[]
 for tr in s.find_all('tr'):
  cells=[clean(x.get_text(' ',strip=True)) for x in tr.find_all(['th','td'])]
  if len(cells)<3:continue
  c=club(cells[0]);name=cells[1];reason=cells[2];ret=cells[3] if len(cells)>3 else None
  if c and valid_name(name) and len(reason)>3:
   out.append({'name':name,'club':c,'status':'unavailable','starter':0.0,'appearance':0.0,'availability_type':'injury','reason':reason,'expected_return':ret,'source':source})
 return dedupe(out)

def parse_injury_sections(s,source):
 lines=[clean(x) for x in s.stripped_strings if clean(x)];out=[];c=None;section=None
 for i,line in enumerate(lines):
  tc=club(line)
  if tc:c=tc;section=None;continue
  low=norm(line)
  if low.startswith('infortunati'):section='injury';continue
  if low.startswith('squalificati'):section='suspension';continue
  if low.startswith('in dubbio'):section='doubt';continue
  if low.startswith(('diffidati','panchina','ballottaggi')):section=None;continue
  if not c or not section or low in ('nessuno','nessun calciatore'):continue
  # linked player followed by description
  if valid_name(line) and i+1<len(lines) and len(lines[i+1])>4 and not club(lines[i+1]):
   reason=lines[i+1];doubt=section=='doubt' or bool(re.search(r'in dubbio|da valutare|recuperabile',reason,re.I));status='doubt' if doubt else 'unavailable'
   x={'name':line,'club':c,'status':status,'availability_type':section,'reason':reason,'source':source}
   if status=='unavailable':x.update(starter=0.0,appearance=0.0)
   out.append(x)
 return dedupe(out)

def parse_source(name,html):
 low=name.casefold();s=soup(html);text='\n'.join(clean(x) for x in s.stripped_strings if clean(x))
 if 'lineups_fantacalcio' in low:records=parse_fantacalcio(s,name);kind='lineups'
 elif 'lineups_sosfanta' in low:records=parse_sos(s,name);kind='lineups'
 elif 'lineups_gazzetta' in low:records=parse_gazzetta(s,name);kind='lineups'
 elif 'injuries_official' in low:records=parse_injury_table(s,name);kind='availability'
 elif any(k in low for k in ('injur','infortun','indispon','squal')):records=parse_injury_sections(s,name);kind='availability'
 else:records=[];kind='unsupported'
 return {'records':records,'updated_at':stamp(text),'kind':kind}
