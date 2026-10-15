#!/usr/bin/env python3
"""Buyer Discovery 3.1: public search-feed discovery, no personal-data scraping.

Uses Bing's publicly available RSS search endpoint (availability is not guaranteed)
and optionally user-authorised RSS/Atom URLs supplied in EXTRA_RSS_FEEDS.
Outputs an Excel-friendly CSV plus diagnostics, even when feeds fail.
"""
import csv
import datetime as dt
import email.utils
import html
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

OUT = Path('buyer_opportunities_v3.csv')  # keep existing workflow compatible
DIAG = Path('buyer_discovery_diagnostics.txt')
FIELDS = ['found_at_utc', 'source', 'title', 'url', 'summary', 'location_match', 'intent', 'priority']
SEARCHES = [
    '"looking to buy" "car" "Cape Town"',
    '"want to buy" "bakkie" "Western Cape"',
    '"looking for a car" "Paarl"',
    '"looking for a bakkie" "Cape Town"',
    '"wanted to buy" "vehicle" "Stellenbosch"',
    '"car wanted" "Western Cape"',
    '"bakkie wanted" "Cape Town"',
]
REGIONS = ['western cape', 'cape town', 'paarl', 'stellenbosch', 'bellville',
           'durbanville', 'somerset west', 'brackenfell', 'kuils river', 'wellington',
           'strand', 'goodwood', 'milnerton', 'malmesbury', 'franschhoek', 'piketberg']
BUYER = re.compile(r'\b(?:looking (?:to buy|for)|want(?:ing)? to buy|wanted to buy|in (?:the )?market for|seeking to buy|car wanted|vehicle wanted|bakkie wanted|need to buy)\b', re.I)
VEHICLE = re.compile(r'\b(?:car|vehicle|bakkie|pickup|suv|hatchback|sedan|4x4|ford ranger|toyota hilux|vw polo)\b', re.I)
SELLER = re.compile(r'\b(?:for sale|we sell|selling my|stock available|apply for finance|dealer special)\b', re.I)
USER_AGENT = 'Mozilla/5.0 (compatible; BuyerDiscovery/3.1; public RSS reader)'


def plain(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', value or ''))).strip()


def entries(xml_bytes):
    root = ET.fromstring(xml_bytes)
    found = []
    for item in root.findall('.//item'):
        def get(tag):
            node = item.find(tag)
            return ''.join(node.itertext()).strip() if node is not None else ''
        found.append((get('title'), get('link'), get('description')))
    if found:
        return found
    ns = {'a': 'http://www.w3.org/2005/Atom'}
    for item in root.findall('.//a:entry', ns):
        title = item.findtext('a:title', default='', namespaces=ns)
        summary = item.findtext('a:summary', default='', namespaces=ns)
        link = item.find('a:link', ns)
        url = link.attrib.get('href', '') if link is not None else ''
        found.append((title, url, summary))
    return found


def main():
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    diagnostics = [f'Buyer Discovery 3.1 — {now}', 'Sources are unverified until checked manually.', '']
    feeds = []
    for query in SEARCHES:
        url = 'https://www.bing.com/search?format=rss&q=' + urllib.parse.quote(query)
        feeds.append((f'Bing RSS: {query}', url))
    for i, url in enumerate(os.getenv('EXTRA_RSS_FEEDS', '').split(','), 1):
        url = url.strip()
        if url and urllib.parse.urlparse(url).scheme == 'https':
            feeds.append((f'Authorised feed {i}', url))
    rows, seen = [], set()
    for source, url in feeds:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/rss+xml, application/atom+xml, application/xml, text/xml'})
            with urllib.request.urlopen(req, timeout=18) as response:
                data = response.read(1_500_000)
            items = entries(data)
            kept = 0
            for title, link, summary in items:
                title, summary = plain(title), plain(summary)
                combined = f'{title} {summary}'
                locations = [r for r in REGIONS if r in combined.lower()]
                if not (BUYER.search(combined) and VEHICLE.search(combined) and locations):
                    continue
                if SELLER.search(title):
                    continue
                if not link.startswith(('https://', 'http://')):
                    continue
                key = link.split('#', 1)[0].rstrip('/')
                if key in seen:
                    continue
                seen.add(key)
                priority = 'Review first' if any(r in locations for r in ('paarl', 'stellenbosch', 'cape town')) else 'Review'
                rows.append([now, source, title[:240], link, summary[:500], ', '.join(locations), 'Possible buyer request — unverified', priority])
                kept += 1
            diagnostics.append(f'{source}: accessible; {len(items)} feed items; {kept} possible matches')
        except (urllib.error.URLError, TimeoutError, ET.ParseError, ValueError, OSError) as exc:
            diagnostics.append(f'{source}: UNAVAILABLE — {type(exc).__name__}: {exc}')
        time.sleep(0.4)
    with OUT.open('w', encoding='utf-8-sig', newline='') as fh:
        writer = csv.writer(fh)
        writer.writerow(FIELDS)
        writer.writerows(rows)
    diagnostics += ['', f'Total possible matches: {len(rows)}', 'Zero results can mean no matching posts, inaccessible feeds, or restrictive filters.', 'Do not collect private contact details or send unsolicited messages.', '', 'Manual review: https://www.junkmail.co.za/cars/wanted', 'Manual review: https://www.junkmail.co.za/western-cape/wanted']
    DIAG.write_text('\n'.join(diagnostics) + '\n', encoding='utf-8')
    print(f'Candidate public posts: {len(rows)}')
    print(f'Reports: {OUT} and {DIAG}')
    for line in diagnostics[3:3 + len(feeds)]:
        print(line)


if __name__ == '__main__':
    main()
