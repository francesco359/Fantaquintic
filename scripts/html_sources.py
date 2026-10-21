#!/usr/bin/env python3
"""Parser HTML v6.3 per FantaQuintoc.
Estrazione conservativa di probabili formazioni, infortuni e squalifiche.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from typing import Any
from bs4 import BeautifulSoup

TEAM_MAP = {
    'atalanta':'ATA','bologna':'BOL','cagliari':'CAG','como':'COM',
    'fiorentina':'FIO','frosinone':'FRO','genoa':'GEN','inter':'INT',
    'juventus':'JUV','lazio':'LAZ','lecce':'LEC','milan':'MIL',
    'monza':'MON','napoli':'NAP','parma':'PAR','roma':'ROM',
    'sassuolo':'SAS','torino':'TOR','udinese':'UDI','venezia':'VEN'
}

STOP_WORDS = {
    'panchina','squalificati','diffidati','infortunati','in dubbio',
    'ballottaggi','grafico ballottaggio','presentazione squadre',
    'dettaglio calciatori','ultimo aggiornamento','probabili formazioni'
}

NOISE = re.compile(
    r'\b(mercato|vittoria|quote|pronostico|pubblicità|cookie|newsletter|'
    r'abbonati|scarica|leggi|diretta|classifica|calendario|giornata|'
    r'campionato|redazione|condividi|video|news)\b', re.I
)

NAME_TOKEN = r"[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ.'’\-]*"
NAME_RE = re.compile(
    rf"^(?P<name>{NAME_TOKEN}(?:\s+{NAME_TOKEN}){{0,3}})\s+"
    r"(?P<pct>100|[1-9]?\d(?:[.,]\d)?)\s*%$"
)
PAIR_RE = re.compile(
    rf"(?P<name>{NAME_TOKEN}(?:\s+{NAME_TOKEN}){{0,3}})\s+"
    r"(?P<pct>100|[1-9]?\d(?:[.,]\d)?)\s*%"
)


def clean(value: str) -> str:
    value = unicodedata.normalize('NFKC', value or '').replace('\xa0', ' ')
    return re.sub(r'\s+', ' ', value).strip()


def normalize(value: str) -> str:
    value = clean(value).casefold().replace('ø', 'o')
    return re.sub(r'[^a-z0-9]+', ' ', value).strip()


def soup(html: str) -> BeautifulSoup:
    page = BeautifulSoup(html, 'html.parser')
    for tag in page(['script', 'style', 'noscript', 'svg', 'iframe']):
        tag.decompose()
    return page


def visible_lines(page: BeautifulSoup) -> list[str]:
    return [clean(x) for x in page.stripped_strings if clean(x)]


def detect_updated_at(text: str) -> str | None:
    m = re.search(
        r'(?:Ultimo aggiornamento|Aggiornato(?: il)?|Al)\s*'
        r'(\d{1,2}/\d{1,2}/\d{4})(?:\s*[-–]\s*(\d{1,2}:\d{2}))?',
        text, re.I
    )
    if not m:
        return None
    try:
        dt = datetime.strptime(
            m.group(1) + ' ' + (m.group(2) or '00:00'),
            '%d/%m/%Y %H:%M'
        )
        return dt.isoformat(timespec='minutes') + '+02:00'
    except ValueError:
        return None


def team_from_text(value: str) -> str | None:
    key = normalize(value)
    if key in TEAM_MAP:
        return TEAM_MAP[key]
    for name, code in TEAM_MAP.items():
        if re.fullmatch(rf'{re.escape(name)}(?:\s+\d[-–]\d[-–]\d[-–]\d)?', key):
            return code
    return None


def valid_player_name(name: str) -> bool:
    name = clean(name).strip(' -:;,')
    low = normalize(name)
    if not 2 <= len(name) <= 42:
        return False
    if low in STOP_WORDS or NOISE.search(name):
        return False
    words = name.split()
    if not 1 <= len(words) <= 4:
        return False
    if any(len(x) > 18 for x in words):
        return False
    return bool(re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ.'’\- ]+", name))


def json_ld_lineups(page: BeautifulSoup, source: str) -> list[dict[str, Any]]:
    """Tenta prima eventuali dati strutturati incorporati nella pagina."""
    records: list[dict[str, Any]] = []
    for node in page.find_all('script', type='application/ld+json'):
        try:
            payload = json.loads(node.string or '')
        except Exception:
            continue
        stack = payload if isinstance(payload, list) else [payload]
        for item in stack:
            if not isinstance(item, dict):
                continue
            name = item.get('name')
            pct = item.get('probability') or item.get('starter_probability')
            club = item.get('team') or item.get('club')
            if name and pct is not None and valid_player_name(str(name)):
                try:
                    pct = float(str(pct).replace('%', '').replace(',', '.'))
                except ValueError:
                    continue
                records.append({
                    'name': clean(str(name)), 'club': team_from_text(str(club)) or club,
                    'starter': pct, 'status': 'available', 'source': source
                })
    return records


def parse_lineups(html: str, source: str = 'lineups') -> dict[str, Any]:
    page = soup(html)
    lines = visible_lines(page)
    records = json_ld_lineups(page, source)
    seen = {(normalize(r['name']), r.get('club')) for r in records}

    current_club: str | None = None
    in_lineup_block = False
    team_player_count = 0

    for line in lines:
        low = normalize(line)
        club = team_from_text(line)
        if club:
            current_club = club
            in_lineup_block = True
            team_player_count = 0
            continue

        if low in STOP_WORDS:
            if low in {'squalificati','diffidati','infortunati','in dubbio',
                       'presentazione squadre','dettaglio calciatori'}:
                in_lineup_block = False
            elif low == 'panchina':
                in_lineup_block = True
            continue

        if not current_club or not in_lineup_block:
            continue

        candidates = []
        exact = NAME_RE.match(line)
        if exact:
            candidates = [exact]
        elif len(line) <= 180 and not NOISE.search(line):
            candidates = list(PAIR_RE.finditer(line))

        for match in candidates:
            name = clean(match.group('name')).strip(' -:;,')
            if not valid_player_name(name):
                continue
            pct = float(match.group('pct').replace(',', '.'))
            key = (normalize(name), current_club)
            if key in seen:
                continue
            seen.add(key)
            records.append({
                'name': name,
                'club': current_club,
                'starter': pct,
                'status': 'available',
                'source': source
            })
            team_player_count += 1

        # Una formazione completa non deve inglobare il resto dell'articolo.
        if team_player_count >= 28:
            in_lineup_block = False

    return {
        'records': records,
        'updated_at': detect_updated_at('\n'.join(lines)),
        'kind': 'lineups'
    }


def parse_availability(html: str, source: str = 'injuries') -> dict[str, Any]:
    page = soup(html)
    lines = visible_lines(page)
    records: list[dict[str, Any]] = []
    club: str | None = None
    section: str | None = None

    for line in lines:
        detected = team_from_text(line)
        if detected:
            club = detected
            section = None
            continue

        low = normalize(line)
        if low.startswith('infortunati'):
            section = 'injury'
            line = clean(re.sub(r'^infortunati\s*:?', '', line, flags=re.I))
        elif low.startswith('squalificati'):
            section = 'suspension'
            line = clean(re.sub(r'^squalificati\s*:?', '', line, flags=re.I))
        elif low.startswith('in dubbio'):
            section = 'doubt'
            line = clean(re.sub(r'^in dubbio\s*:?', '', line, flags=re.I))
        elif low.startswith(('diffidati','panchina','ballottaggi')):
            section = None
            continue

        if not club or not section or not line or low in {'nessuno','nessun calciatore'}:
            continue

        chunks = [clean(x) for x in re.split(r'\s*[;•]\s*', line) if clean(x)]
        for chunk in chunks:
            m = re.match(
                r"^([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ.'’\- ]{1,34}?)"
                r"(?:\s+-\s+|\s{2,})(.+)$", chunk
            )
            if not m:
                continue
            name, reason = clean(m.group(1)), clean(m.group(2))
            if not valid_player_name(name) or len(reason) < 4:
                continue
            doubtful = section == 'doubt' or re.search(
                r'in dubbio|da valutare|recuperabile|tentativo di recupero', reason, re.I
            )
            status = 'doubt' if doubtful else 'unavailable'
            record = {
                'name': name, 'club': club, 'status': status,
                'availability_type': section, 'reason': reason, 'source': source
            }
            if status == 'unavailable':
                record.update(starter=0.0, appearance=0.0)
            records.append(record)

    return {
        'records': records,
        'updated_at': detect_updated_at('\n'.join(lines)),
        'kind': 'availability'
    }


def parse_source(name: str, html: str) -> dict[str, Any]:
    low = name.casefold()
    if any(k in low for k in ('lineup', 'formazion')):
        return parse_lineups(html, name)
    if any(k in low for k in ('injur', 'infortun', 'indispon', 'squal')):
        return parse_availability(html, name)
    return {
        'records': [],
        'updated_at': detect_updated_at('\n'.join(visible_lines(soup(html)))),
        'kind': 'unsupported'
    }
