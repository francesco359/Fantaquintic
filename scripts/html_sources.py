#!/usr/bin/env python3
"""Parser HTML conservativi per FantaQuintoc.
Non inventano valori: producono record solo quando nome e percentuale/stato
sono esplicitamente presenti nel testo della pagina.
"""
from __future__ import annotations
import re
import unicodedata
from datetime import datetime
from typing import Any
from bs4 import BeautifulSoup

TEAM_MAP={
 'atalanta':'ATA','bologna':'BOL','cagliari':'CAG','como':'COM','fiorentina':'FIO',
 'frosinone':'FRO','genoa':'GEN','inter':'INT','juventus':'JUV','lazio':'LAZ',
 'lecce':'LEC','milan':'MIL','monza':'MON','napoli':'NAP','parma':'PAR','roma':'ROM',
 'sassuolo':'SAS','torino':'TOR','udinese':'UDI','venezia':'VEN'
}
HEADINGS=set(TEAM_MAP)|{'panchina','squalificati','diffidati','infortunati','in dubbio','ballottaggi'}

def clean(x:str)->str:
 x=unicodedata.normalize('NFKC',x or '').replace('\xa0',' ')
 return re.sub(r'\s+',' ',x).strip()

def soup_text(html:str)->str:
 soup=BeautifulSoup(html,'html.parser')
 for tag in soup(['script','style','noscript','svg']): tag.decompose()
 return '\n'.join(clean(x) for x in soup.stripped_strings if clean(x))

def detect_updated_at(text:str)->str|None:
 m=re.search(r'(?:Ultimo aggiornamento|Aggiornato(?: il)?|Al)\s*(\d{1,2}/\d{1,2}/\d{4})(?:\s*[-–]\s*(\d{1,2}:\d{2}))?',text,re.I)
 if not m:return None
 try:
  dt=datetime.strptime(m.group(1)+' '+(m.group(2) or '00:00'),'%d/%m/%Y %H:%M')
  return dt.isoformat(timespec='minutes')+'+02:00'
 except ValueError:return None

def find_club_context(lines:list[str],i:int)->str|None:
 for j in range(i,max(-1,i-80),-1):
  low=lines[j].casefold().strip(' :')
  if low in TEAM_MAP:return TEAM_MAP[low]
 return None

def parse_lineups(html:str,source='lineups')->dict[str,Any]:
 """Estrae coppie Nome 90% dal testo visibile delle probabili formazioni."""
 text=soup_text(html); lines=text.splitlines(); records=[]; seen=set()
 pat=re.compile(r"^(.{2,55}?)\s+(100|[1-9]?\d(?:[.,]\d)?)\s*%$")
 inline=re.compile(r"([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ.'’ -]{1,45}?)\s+(100|[1-9]?\d(?:[.,]\d)?)\s*%")
 for i,line in enumerate(lines):
  matches=[]
  m=pat.match(line)
  if m:matches=[m]
  else:matches=list(inline.finditer(line))
  for m in matches:
   name=clean(m.group(1)).strip(' -:;,')
   if name.casefold() in HEADINGS or len(name)<2:continue
   pct=float(m.group(2).replace(',','.')); club=find_club_context(lines,i)
   key=(name.casefold(),club)
   if key in seen:continue
   seen.add(key)
   records.append({'name':name,'club':club,'starter':pct,'status':'available','source':source})
 return {'records':records,'updated_at':detect_updated_at(text),'kind':'lineups'}

def section_records(html:str,source='injuries')->dict[str,Any]:
 """Estrae indisponibili/squalificati con prudenza dalle sezioni squadra."""
 text=soup_text(html); lines=text.splitlines(); records=[]; club=None; section=None
 for line in lines:
  low=line.casefold().strip(' :')
  if low in TEAM_MAP:club=TEAM_MAP[low];section=None;continue
  if low.startswith('infortunati'):section='injury';line=clean(re.sub(r'^infortunati\s*:?', '',line,flags=re.I))
  elif low.startswith('squalificati'):section='suspension';line=clean(re.sub(r'^squalificati\s*:?', '',line,flags=re.I))
  elif low.startswith('in dubbio'):section='doubt';line=clean(re.sub(r'^in dubbio\s*:?', '',line,flags=re.I))
  elif low.startswith(('diffidati','panchina','ballottaggi')):section=None;continue
  if not club or not section or not line or line in {'-','Nessuno','Nessun calciatore'}:continue
  # Formato editoriale più comune: Nome - descrizione oppure Nome descrizione lunga
  chunks=[clean(x) for x in re.split(r'\s*[;•]\s*',line) if clean(x)]
  for chunk in chunks:
   m=re.match(r"^([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ.'’ -]{1,35}?)(?:\s+-\s+|\s{2,})(.+)$",chunk)
   if not m:continue
   name,reason=clean(m.group(1)),clean(m.group(2))
   if len(reason)<4:continue
   status='doubt' if section=='doubt' or re.search(r'in dubbio|da valutare|recuperabile',reason,re.I) else 'unavailable'
   rec={'name':name,'club':club,'status':status,'source':source,'availability_type':section,'reason':reason}
   if status=='unavailable':rec.update(starter=0.0,appearance=0.0)
   records.append(rec)
 return {'records':records,'updated_at':detect_updated_at(text),'kind':'availability'}

def parse_source(name:str,html:str)->dict[str,Any]:
 low=name.casefold()
 if any(k in low for k in ('lineup','formazion')):return parse_lineups(html,name)
 if any(k in low for k in ('injur','infortun','indispon','squal')):return section_records(html,name)
 return {'records':[],'updated_at':detect_updated_at(soup_text(html)),'kind':'unknown'}
