#!/usr/bin/env python3
from __future__ import annotations
import re, unicodedata
from datetime import datetime
from typing import Any
from bs4 import BeautifulSoup
TEAM_MAP={'atalanta':'ATA','bologna':'BOL','cagliari':'CAG','como':'COM','fiorentina':'FIO','frosinone':'FRO','genoa':'GEN','inter':'INT','juventus':'JUV','lazio':'LAZ','lecce':'LEC','milan':'MIL','monza':'MON','napoli':'NAP','parma':'PAR','roma':'ROM','sassuolo':'SAS','torino':'TOR','udinese':'UDI','venezia':'VEN'}
NOISE=re.compile(r'\b(mercato|vittoria|quote|pronostico|cookie|newsletter|giornata|campionato|pubblicità)\b',re.I)
def clean(x):return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',x or '').replace('\xa0',' ')).strip()
def norm(x):return re.sub(r'[^a-z0-9]+',' ',clean(x).casefold().replace('ø','o')).strip()
def page(html):
 s=BeautifulSoup(html,'html.parser')
 for t in s(['script','style','noscript','svg','iframe']):t.decompose()
 return s
def valid_name(x):
 x=clean(x);return 1<=len(x.split())<=4 and 2<=len(x)<=45 and not NOISE.search(x) and bool(re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ.'’\- ]+",x))
def updated(text):
 m=re.search(r'(?:Ultimo aggiornamento|Aggiornato(?: il)?|Al)\s*(\d{1,2}/\d{1,2}/\d{4})(?:\s*[-–,]\s*(?:ore\s*)?(\d{1,2}:\d{2}))?',text,re.I)
 if not m:return None
 try:return datetime.strptime(m.group(1)+' '+(m.group(2)or'00:00'),'%d/%m/%Y %H:%M').isoformat(timespec='minutes')+'+02:00'
 except:return None
def dom_links(s,source):
 out=[];seen=set();href=re.compile(r'/serie-a/squadre/([^/]+)/[^/]+/\d+',re.I);pct=re.compile(r'^(100|[1-9]?\d(?:[.,]\d)?)\s*%$')
 for a in s.find_all('a',href=True):
  m=href.search(a.get('href',''));name=clean(a.get_text(' ',strip=True))
  if not m or not valid_name(name):continue
  club=TEAM_MAP.get(norm(m.group(1)));value=None;count=0
  for node in a.next_elements:
   if node is not a and getattr(node,'name',None)=='a':break
   if isinstance(node,str):
    z=clean(node)
    if not z:continue
    count+=1;q=pct.match(z)
    if q:value=float(q.group(1).replace(',','.'));break
    if count>6:break
  if value is not None and (norm(name),club) not in seen:
   seen.add((norm(name),club));out.append({'name':name,'club':club,'starter':value,'status':'available','source':source})
 return out
def text_percentages(s,source):
 lines=[clean(x) for x in s.stripped_strings if clean(x)];out=[];seen=set();club=None
 # Supports "Name 90%" and "90% Name"; team context comes from nearest team heading/text.
 a=re.compile(r"^([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ.'’\- ]{1,42}?)\s+(100|[1-9]?\d(?:[.,]\d)?)%$")
 b=re.compile(r"^(100|[1-9]?\d(?:[.,]\d)?)%\s+([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ.'’\- ]{1,42})$")
 for line in lines:
  low=norm(line)
  if low in TEAM_MAP:club=TEAM_MAP[low];continue
  m=a.match(line);rev=False
  if not m:m=b.match(line);rev=True
  if not m or not club:continue
  name=clean(m.group(2) if rev else m.group(1));val=float((m.group(1) if rev else m.group(2)).replace(',','.'))
  key=(norm(name),club)
  if valid_name(name) and key not in seen:seen.add(key);out.append({'name':name,'club':club,'starter':val,'status':'available','source':source})
 return out
def parse_lineups(html,source='lineups'):
 s=page(html);text='\n'.join(clean(x) for x in s.stripped_strings if clean(x));records=dom_links(s,source)
 seen={(norm(x['name']),x.get('club')) for x in records}
 for x in text_percentages(s,source):
  if (norm(x['name']),x.get('club')) not in seen:records.append(x);seen.add((norm(x['name']),x.get('club')))
 return {'records':records,'updated_at':updated(text),'kind':'lineups'}
def parse_availability(html,source='injuries'):
 s=page(html);lines=[clean(x) for x in s.stripped_strings if clean(x)];out=[];club=None;section=None
 for line in lines:
  low=norm(line)
  if low in TEAM_MAP:club=TEAM_MAP[low];section=None;continue
  if low.startswith('infortunati'):section='injury';continue
  if low.startswith('squalificati'):section='suspension';continue
  if low.startswith('in dubbio'):section='doubt';continue
  if not club or not section:continue
  m=re.match(r"^([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ.'’\- ]{1,34}?)(?:\s+-\s+|\s{2,})(.+)$",line)
  if not m:continue
  name,reason=clean(m.group(1)),clean(m.group(2));status='doubt' if section=='doubt' or re.search(r'in dubbio|da valutare|recuperabile',reason,re.I) else 'unavailable'
  if valid_name(name):
   r={'name':name,'club':club,'status':status,'reason':reason,'availability_type':section,'source':source}
   if status=='unavailable':r.update(starter=0.0,appearance=0.0)
   out.append(r)
 return {'records':out,'updated_at':updated('\n'.join(lines)),'kind':'availability'}
def parse_source(name,html):
 low=name.casefold()
 if 'lineup' in low or 'formazion' in low:return parse_lineups(html,name)
 if any(x in low for x in ('injur','infortun','indispon','squal')):return parse_availability(html,name)
 return {'records':[],'updated_at':None,'kind':'unsupported'}
