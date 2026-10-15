#!/usr/bin/env python3
"""Discover possible buyer requests from public RSS feeds. No private data collection."""
import csv, datetime as dt, email.utils, html, os, re, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

OUT = Path('buyer_opportunities_v3.csv')
FEEDS = [
    ('Reddit South Africa cars', 'https://www.reddit.com/r/carsSouthAfrica/search.rss?q=' + urllib.parse.quote('"looking for" OR "want to buy" OR "buying"') + '&restrict_sr=1&sort=new&t=month'),
    ('Reddit South Africa', 'https://www.reddit.com/r/southafrica/search.rss?q=' + urllib.parse.quote('"looking for a car" OR "buy a car"') + '&restrict_sr=1&sort=new&t=month'),
    ('Reddit Cape Town', 'https://www.reddit.com/r/capetown/search.rss?q=' + urllib.parse.quote('"looking for a car" OR "buy a bakkie" OR "car wanted"') + '&restrict_sr=1&sort=new&t=month'),
]
# Add only RSS/Atom URLs you are authorized to access, separated by commas.
for n, url in enumerate(os.getenv('EXTRA_RSS_FEEDS', '').split(','), 1):
    url = url.strip()
    if url.startswith('https://'):
        FEEDS.append((f'Additional feed {n}', url))

INTENT = re.compile(r'\b(looking for|looking to buy|want to buy|wanted to buy|need to buy|planning to buy|in the market for|searching for|buying a|purchase a|car wanted|vehicle wanted|bakkie wanted)\b', re.I)
VEHICLE = re.compile(r'\b(car|cars|vehicle|bakkie|suv|hatchback|sedan|pickup|ford ranger|hilux|polo|corolla|np200|double cab)\b', re.I)
NEGATIVE = re.compile(r'\b(for sale|selling my|we buy cars|cash for cars|scrap cars|spares|breaking for parts|wanted: mechanic|job wanted)\b', re.I)
WESTERN = re.compile(r'\b(western cape|cape town|paarl|stellenbosch|somerset west|franschhoek|wellington|bellville|durbanville|brackenfell|strand|parow|cape winelands)\b', re.I)
TAG = re.compile(r'<[^>]+>')

def clean(s):
    return re.sub(r'\s+', ' ', html.unescape(TAG.sub(' ', s or ''))).strip()

def parse_date(value):
    if not value: return None
    try:
        x = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        try: x = email.utils.parsedate_to_datetime(value)
        except (ValueError, TypeError): return None
    return x.replace(tzinfo=x.tzinfo or dt.timezone.utc).astimezone(dt.timezone.utc)

def entries(xml_bytes):
    root = ET.fromstring(xml_bytes)
    if root.tag.endswith('feed'):
        ns = {'a': 'http://www.w3.org/2005/Atom'}
        for entry in root.findall('a:entry', ns):
            link = next((x.get('href','') for x in entry.findall('a:link', ns) if x.get('rel','alternate') == 'alternate'), '')
            if not link:
                link = next((x.get('href','') for x in entry.findall('a:link', ns)), '')
            yield (entry.findtext('a:title', '', ns), entry.findtext('a:content', '', ns) or entry.findtext('a:summary', '', ns), link, entry.findtext('a:updated', '', ns) or entry.findtext('a:published', '', ns))
    else:
        for entry in root.findall('.//item'):
            yield (entry.findtext('title',''), entry.findtext('description',''), entry.findtext('link',''), entry.findtext('pubDate',''))

def assess(title, description, link, date, source, now):
    text = clean(title + ' ' + description)
    if not INTENT.search(text) or not VEHICLE.search(text) or NEGATIVE.search(clean(title)):
        return None
    posted = parse_date(date)
    if not posted or posted > now + dt.timedelta(days=1) or (now-posted).days > 30:
        return None
    if not link.startswith('https://'):
        return None
    region = bool(WESTERN.search(text)) or 'capetown' in source.lower()
    score = 60 + (25 if region else 0) + (10 if (now-posted).days <= 7 else 0)
    return [source, clean(title)[:250], 'Western Cape mentioned' if region else 'Location unconfirmed', posted.date().isoformat(), score, link, 'Unverified - review original post']

def main():
    now = dt.datetime.now(dt.timezone.utc)
    found, seen, errors = [], set(), []
    for source, url in FEEDS:
        try:
            req = urllib.request.Request(url, headers={'User-Agent':'PreOwnedPaarlBuyerDiscovery/3.0 (public RSS reader; contact via original platform)', 'Accept':'application/atom+xml,application/rss+xml,application/xml'})
            with urllib.request.urlopen(req, timeout=18) as resp:
                data = resp.read(2_000_000)
            for title, desc, link, date in entries(data):
                row = assess(title, desc, link, date, source, now)
                if row and link not in seen:
                    seen.add(link); found.append(row)
        except Exception as exc:
            errors.append(f'{source}: {type(exc).__name__}: {exc}')
    found.sort(key=lambda row: (-row[4], row[3]), reverse=False)
    with OUT.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['Source','Title','Location assessment','Published','Priority score','Original URL','Verification'])
        writer.writerows(found)
    Path('buyer_discovery_status.txt').write_text('Run UTC: '+now.isoformat()+'\nCandidates: '+str(len(found))+'\nFeeds checked: '+str(len(FEEDS))+'\nErrors:\n'+ ('\n'.join(errors) if errors else 'None')+'\n\nNo result is a verified buyer. RSS feeds may be blocked or have no matches. Review all links before outreach.\n', encoding='utf-8')
    print('Candidate public posts:', len(found))
    for e in errors: print('Feed unavailable:', e)

if __name__ == '__main__': main()
