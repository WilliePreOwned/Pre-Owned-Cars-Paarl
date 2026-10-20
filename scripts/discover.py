#!/usr/bin/env python3
"""Willie Buyer Radar 4.0: permitted RSS discovery, scoring, diagnostics.
No login scraping, private-data extraction, or unsolicited contact automation.
"""
import csv
import datetime as dt
import email.utils
import hashlib
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

OUT = Path('buyer_opportunities_v3.csv')
DIAG = Path('buyer_discovery_diagnostics.txt')
STATE = Path('buyer_radar_seen.json')
FIELDS = ['found_at_utc', 'source', 'title', 'url', 'summary', 'location_match', 'intent', 'priority', 'score', 'published_utc', 'first_seen_utc', 'new_this_run']
SEARCHES = [
    '"looking for" "bakkie" "Cape Town"',
    '"looking for" "car" "Paarl"',
    '"want to buy" "car" "Western Cape"',
    '"need a car" "Cape Town"',
    '"car wanted" "Western Cape"',
    '"bakkie wanted" "Cape Town"',
    '"looking for" "automatic" "car" "Cape Town"',
    '"looking for" "SUV" "Western Cape"',
    '"vehicle wanted" "Stellenbosch"',
]
REGIONS = ['western cape','cape town','paarl','stellenbosch','bellville','durbanville','somerset west','brackenfell','kuils river','wellington','strand','goodwood','milnerton','malmesbury','franschhoek','piketberg','george','paarl']
BUYER = re.compile(r'\b(?:looking (?:to buy|for)|want(?:ing)? to buy|wanted to buy|in (?:the )?market for|seeking (?:to buy|a)|car wanted|vehicle wanted|bakkie wanted|need (?:to buy|a|an)|anyone (?:have|selling)|where can i (?:buy|find)|searching for)\b', re.I)
VEHICLE = re.compile(r'\b(?:car|vehicle|bakkie|pickup|suv|hatchback|sedan|4x4|ranger|hilux|polo|corolla|automatic|hatch|double cab|d[ -]?cab|fortuner)\b', re.I)
SELLER = re.compile(r'\b(?:for sale|we sell|selling my|stock available|apply for finance|dealer special|available now|our showroom|book a test drive|contact us today|buy from us|sale price|special offer)\b', re.I)
BUDGET = re.compile(r'\b(?:budget|under|below|up to|maximum|max|afford|r\s?\d[\d, ]{3,}|\d{2,3}k)\b', re.I)
URGENT = re.compile(r'\b(?:urgent|asap|this week|this month|immediately|ready to buy|cash buyer)\b', re.I)
USER_AGENT = 'WillieBuyerRadar/4.0 (public RSS reader; contact via source website)'
MAX_DAYS = max(1, int(os.getenv('MAX_POST_AGE_DAYS', '45')))
MIN_SCORE = max(0, int(os.getenv('MIN_LEAD_SCORE', '45')))


def plain(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', value or ''))).strip()


def entries(xml_bytes):
    root = ET.fromstring(xml_bytes)
    result = []
    for item in root.findall('.//item'):
        def get(tag):
            n = item.find(tag)
            return ''.join(n.itertext()).strip() if n is not None else ''
        result.append((get('title'), get('link'), get('description'), get('pubDate')))
    if result:
        return result
    ns = {'a':'http://www.w3.org/2005/Atom'}
    for item in root.findall('.//a:entry', ns):
        link = next((x.attrib.get('href', '') for x in item.findall('a:link', ns) if x.attrib.get('rel','alternate') == 'alternate'), '')
        result.append((item.findtext('a:title', default='', namespaces=ns), link,
                       item.findtext('a:summary', default='', namespaces=ns) or item.findtext('a:content', default='', namespaces=ns),
                       item.findtext('a:updated', default='', namespaces=ns) or item.findtext('a:published', default='', namespaces=ns)))
    return result


def published(value):
    if not value:
        return None
    try:
        date = email.utils.parsedate_to_datetime(value)
        if date is None:
            date = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        return date.replace(tzinfo=dt.timezone.utc) if date.tzinfo is None else date.astimezone(dt.timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def score(text, locations):
    points = 0
    if BUYER.search(text): points += 40
    if VEHICLE.search(text): points += 20
    if locations: points += 15
    if any(x in locations for x in ('paarl','stellenbosch','cape town')): points += 10
    if BUDGET.search(text): points += 10
    if URGENT.search(text): points += 5
    return min(points, 100)


def main():
    now_dt = dt.datetime.now(dt.timezone.utc)
    now = now_dt.isoformat(timespec='seconds')
    diagnostics = [f'Willie Buyer Radar 4.0 — {now}', 'All leads require manual verification; RSS availability varies.', '']
    feeds = [(f'Bing RSS: {q}', 'https://www.bing.com/search?format=rss&q=' + urllib.parse.quote(q)) for q in SEARCHES]
    for i, url in enumerate(os.getenv('EXTRA_RSS_FEEDS', '').split(','), 1):
        url = url.strip()
        if url.startswith('https://'):
            feeds.append((f'Authorised feed {i}', url))
    try:
        old = json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}
        if not isinstance(old, dict): old = {}
    except (ValueError, OSError):
        old = {}
    # Persist state by committing the JSON to the repo, or supply it as an artifact between runs.
    seen_run, rows, fresh_count = set(), [], 0
    for source, url in feeds:
        try:
            request = urllib.request.Request(url, headers={'User-Agent':USER_AGENT, 'Accept':'application/rss+xml, application/atom+xml, application/xml, text/xml'})
            with urllib.request.urlopen(request, timeout=18) as response:
                data = response.read(1_500_000)
            items = entries(data)
            kept = 0
            for title, link, summary, pub in items:
                title, summary = plain(title), plain(summary)
                text = f'{title} {summary}'
                locations = sorted(set(r for r in REGIONS if re.search(r'(?<!\w)' + re.escape(r) + r'(?!\w)', text, re.I)))
                if not BUYER.search(text) or not VEHICLE.search(text): continue
                if SELLER.search(title): continue
                if not locations and os.getenv('REQUIRE_LOCATION', 'true').lower() == 'true': continue
                if not link.startswith(('https://','http://')): continue
                if urllib.parse.urlparse(link).hostname in (None, 'localhost'): continue
                date = published(pub)
                if date and (now_dt - date).days > MAX_DAYS: continue
                value = score(text, locations)
                if value < MIN_SCORE: continue
                normalized = link.split('#',1)[0].rstrip('/')
                key = hashlib.sha256(normalized.encode()).hexdigest()
                if key in seen_run: continue
                seen_run.add(key)
                is_new = key not in old
                if is_new: fresh_count += 1
                first_seen = old.setdefault(key, now)
                priority = 'High' if value >= 85 else 'Medium' if value >= 65 else 'Review'
                rows.append([now, source, title[:240], link, summary[:500], ', '.join(locations),
                             'Possible buyer request — unverified', priority, value,
                             date.isoformat() if date else '', first_seen, 'yes' if is_new else 'no'])
                kept += 1
            diagnostics.append(f'{source}: accessible; {len(items)} feed items; {kept} qualifying matches')
        except (urllib.error.URLError, TimeoutError, ET.ParseError, ValueError, OSError) as exc:
            diagnostics.append(f'{source}: UNAVAILABLE — {type(exc).__name__}: {exc}')
        time.sleep(0.2)
    rows.sort(key=lambda r: int(r[8]), reverse=True)
    with OUT.open('w', encoding='utf-8-sig', newline='') as fh:
        writer = csv.writer(fh); writer.writerow(FIELDS); writer.writerows(rows)
    STATE.write_text(json.dumps(old, indent=2) + '\n', encoding='utf-8')
    diagnostics += ['', f'Total qualifying matches this run: {len(rows)}', f'New compared with saved state: {fresh_count}',
                    'If state is not persisted between GitHub Actions runs, all results will appear new.',
                    'Zero results can mean inaccessible feeds, no recent matching posts, or restrictive filters.',
                    'Never treat a public search snippet as a verified individual buyer or extract private contact information.']
    DIAG.write_text('\n'.join(diagnostics)+'\n', encoding='utf-8')
    print(f'Candidates: {len(rows)}; new: {fresh_count}')
    for line in diagnostics[3:3+len(feeds)]: print(line)

if __name__ == '__main__': main()
