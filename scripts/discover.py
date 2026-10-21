#!/usr/bin/env python3
"""Willie Buyer Radar 5.3 — public RSS buyer-request discovery.

Uses public search RSS and optional authorised RSS feeds only. No login, private
profiles, personal contact harvesting, or circumvention of access controls.
"""
import collections
import csv
import datetime as dt
import email.utils
import hashlib
import html
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JSON_OUT = ROOT / 'buyer-radar-data.json'
CSV_OUT = ROOT / 'buyer_opportunities_v5.csv'
DIAG_OUT = ROOT / 'buyer_discovery_diagnostics_v5.txt'
STATE = ROOT / 'buyer_radar_seen_v5.json'
UTC = dt.timezone.utc

# Broad Bing searches remain useful as a backup, but do not reliably index
# social buyer posts. Source-targeted queries can improve relevance.
SEARCHES = [
    'site:reddit.com/r/capetown "looking to buy" car',
    'site:reddit.com/r/capetown "looking for" bakkie',
    'site:reddit.com/r/askSouthAfrica "looking to buy" car "Cape Town"',
    'site:reddit.com/r/southafrica "want to buy" car "Cape Town"',
    'site:reddit.com "anyone selling" car "Cape Town"',
    'site:reddit.com "looking for a car" "Paarl"',
    '"looking to buy a car" "Cape Town" -dealer -dealership',
    '"want to buy a car" "Western Cape" -dealer',
    '"need a reliable car" "Cape Town" -dealer',
    '"bakkie wanted" "Western Cape" -dealer',
    '"vehicle wanted" "Paarl" -dealer',
    '"looking for a used car" "Bellville" -dealership',
    '"looking for a double cab" "Western Cape" -dealer',
    '"looking to buy a Hilux" "Cape Town" -dealer',
    '"looking for a Ford Ranger" "Western Cape" -dealer',
    '"anyone selling a bakkie" "Paarl"',
    '"soek n bakkie" "Kaapstad"',
    '"soek n kar" "Paarl"',
]
LOCATIONS = [
    'western cape', 'cape town', 'paarl', 'stellenbosch', 'bellville', 'durbanville',
    'somerset west', 'brackenfell', 'kuils river', 'wellington', 'strand', 'goodwood',
    'milnerton', 'malmesbury', 'franschhoek', 'piketberg', 'george', 'table view',
    'cape winelands', 'kaapstad', 'wes-kaap', 'parow', 'kraaifontein', 'claremont',
    'mitchells plain', 'muizenberg', 'blouberg', 'hermanus', 'oudtshoorn', 'knysna',
    'mossel bay', 'vredenburg', 'saldanha', 'langebaan', 'worcester', 'ceres',
]
INTENT = re.compile(
    r"\b(?:looking\s+(?:to\s+buy|for)|want(?:ing)?\s+to\s+buy|need\s+(?:a|an|to\s+buy)|"
    r"in\s+the\s+market\s+for|seeking\s+(?:a|to\s+buy)|searching\s+for|"
    r"(?:car|vehicle|bakkie)\s+wanted|where\s+can\s+i\s+(?:buy|find)|"
    r"anyone\s+(?:selling|have)|does\s+anyone\s+(?:have|sell)|"
    r"soek\s+(?:'n|n|vir)|op\s+soek\s+na)\b", re.I)
VEHICLE = re.compile(
    r'\b(?:car|cars|vehicle|vehicles|bakkie|bakkies|pickup|suv|hatchback|sedan|'
    r'4x4|ranger|hilux|polo|corolla|automatic|double\s+cab|d[ -]?cab|'
    r'fortuner|kar|motor|voertuig|corsa|swift|picanto|kwid|i20|creta|'
    r'tiggo|duster|navara|np200|etios|quantum)\b', re.I)
SELLER = re.compile(
    r'\b(?:for sale|we sell|selling my|stock available|apply for finance|'
    r'dealer special|available now|our showroom|book a test drive|'
    r'contact us today|buy from us|sale price|special offer|on sale|'
    r'price reduced|we have stock|inventory|cars for sale|vehicles for sale|'
    r'buying guide|how to buy|tips for buying|shop now|browse our stock)\b', re.I)
BUDGET = re.compile(r'\b(?:budget|under|below|up to|maximum|max|afford|r\s?\d[\d, ]{3,}|\d{2,3}k)\b', re.I)
URGENT = re.compile(r'\b(?:urgent|asap|this week|this month|immediately|ready to buy|cash buyer)\b', re.I)
BLOCKED_DOMAINS = (
    'wikipedia.org', 'wiktionary.org', 'merriam-webster.com', 'dictionary.com',
    'thefreedictionary.com', 'imdb.com', 'rottentomatoes.com', 'thesaurus.com',
    'collinsdictionary.com', 'cambridge.org', 'britannica.com', 'tvguide.com',
    'wordreference.com', 'yourdictionary.com',
)
FIELDS = ['first_seen_utc','published_utc','source','title','url','summary',
          'locations','score','priority','new_this_run']


def clean(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', value or ''))).strip()


def parse_date(value):
    """Accept Atom ISO-8601 and RSS RFC-2822 timestamps, including Reddit Atom."""
    if not value:
        return None
    value = value.strip()
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (TypeError, ValueError):
        try:
            parsed = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed is None:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def parse_feed(raw):
    root = ET.fromstring(raw)
    out = []
    for item in root.findall('.//item'):
        def get(tag):
            node = item.find(tag)
            return ''.join(node.itertext()).strip() if node is not None else ''
        out.append((get('title'), get('link'), get('description'), get('pubDate')))
    ns = {'a': 'http://www.w3.org/2005/Atom'}
    for item in root.findall('.//a:entry', ns):
        link = next((x.get('href', '') for x in item.findall('a:link', ns)
                     if x.get('rel', 'alternate') in ('alternate', None)), '')
        out.append((item.findtext('a:title', '', ns), link,
                    item.findtext('a:summary', '', ns) or item.findtext('a:content', '', ns),
                    item.findtext('a:updated', '', ns) or item.findtext('a:published', '', ns)))
    return out


def blocked_domain(url):
    host = (urllib.parse.urlparse(url).hostname or '').lower()
    return any(host == domain or host.endswith('.' + domain) for domain in BLOCKED_DOMAINS)


def matched_locations(text):
    lowered = clean(text).lower()
    return sorted({x for x in LOCATIONS
                   if re.search(r'(?<!\w)' + re.escape(x) + r'(?!\w)', lowered)})


# An actionable lead must express a vehicle purchase, not just contain "looking",
# "car" and "budget" in unrelated parts of a long Reddit discussion.
VEHICLE_WORD = r"(?:car|vehicle|bakkie|pickup|suv|hatchback|sedan|4x4|hilux|ranger|polo|corolla|fortuner|double\s+cab|kar|voertuig|used\s+car|second[ -]?hand\s+car)"
BUY_ACTION = r"(?:buy|buying|purchase|purchasing|get|find|looking\s+for|searching\s+for|need|want|seeking|soek)"
PURCHASE_REQUEST = re.compile(
    rf"\b(?:buy|buying|purchase|purchasing)\b.{{0,55}}?\b{VEHICLE_WORD}\b|"
    rf"\b{VEHICLE_WORD}\b.{{0,12}}?\b(?:to\s+buy|wanted|for\s+purchase)\b|"
    rf"\b(?:looking\s+(?:to\s+buy|for)|need|want|searching\s+for|seeking)\b\s+(?:(?:a|an|the|used|second[ -]?hand|reliable|affordable|new)\s+){{0,4}}{VEHICLE_WORD}\b|"
    rf"\b(?:soek\s+(?:'n|n|vir)|op\s+soek\s+na)\b.{{0,35}}?\b{VEHICLE_WORD}\b",
    re.I)

ADVICE = re.compile(r"\b(?:help\s+with\s+buying|advice\s+(?:on|about)\s+buying|where\s+(?:should|can)\s+i\s+buy|recommend\s+(?:a|me)\s+(?:car|vehicle|bakkie)|what\s+car\s+should\s+i\s+buy)\b", re.I)
UNRELATED = re.compile(r"\b(?:rent(?:ing|al)?\s+(?:a\s+)?(?:flat|apartment|house|room)|looking\s+for\s+(?:a\s+)?(?:job|flat|apartment|house|room|mechanic)|mechanic\s+(?:needed|wanted)|cost\s+of\s+living|salary\s+negotiation)\b", re.I)

def assess(title, summary, published, now, min_score=55, max_age_days=30, source_url=""):
    title = clean(title)
    summary = clean(summary)
    text = (title + ' ' + summary).strip()
    locs = matched_locations(text)
    parsed = urllib.parse.urlparse(source_url)
    is_cpt = parsed.hostname in ('reddit.com', 'www.reddit.com') and parsed.path.lower().startswith('/r/capetown/')
    # A community location is only inferred for an explicitly vehicle-related title.
    title_request = bool(PURCHASE_REQUEST.search(title))
    title_vehicle = bool(VEHICLE.search(title))
    inferred_location = not locs and is_cpt and title_request and title_vehicle
    if inferred_location:
        locs = ['cape town (community; verify location)']
    # Search a short contiguous section: a long post can mention an unrelated
    # purchase and vehicle hundreds of words apart.
    request = title_request or bool(PURCHASE_REQUEST.search(summary[:650]))
    vehicle = bool(VEHICLE.search(text))
    advice = bool(ADVICE.search(text))
    seller = bool(SELLER.search(text))
    unrelated = bool(UNRELATED.search(title))
    score = min(100, 40*request + 20*vehicle + 20*bool(locs) +
                10*bool(BUDGET.search(text)) + 5*bool(URGENT.search(text)) +
                5*title_request)
    reasons = []
    if not request: reasons.append('no clear vehicle purchase request')
    if not vehicle: reasons.append('no vehicle term')
    if not locs: reasons.append('no Western Cape location in result text')
    if seller: reasons.append('seller/advertisement wording')
    if unrelated: reasons.append('unrelated housing, employment or repair request')
    # Do not present undated or stale posts as current buyer opportunities.
    if published is None:
        reasons.append('publication date unavailable')
    elif (now - published).total_seconds() > max_age_days * 86400:
        reasons.append('older than age limit')
    elif (published - now).total_seconds() > 86400:
        reasons.append('publication date in future')
    if score < min_score: reasons.append('below minimum score')
    # Advice posts can be worthwhile conversations, but never confirmed sales leads.
    priority = 'Review' if advice or inferred_location or not title_request else ('High' if score >= 80 else 'Review')
    return score, locs, reasons, inferred_location, priority


def load_seen():
    try:
        state = json.loads(STATE.read_text(encoding='utf-8'))
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def main():
    now = dt.datetime.now(UTC)
    timestamp = now.isoformat(timespec='seconds')
    max_age = int(os.getenv('MAX_POST_AGE_DAYS', '30'))
    min_score = int(os.getenv('MIN_LEAD_SCORE', '55'))
    queries = [('Bing RSS: ' + q,
                'https://www.bing.com/search?format=rss&q=' + urllib.parse.quote(q), False)
               for q in SEARCHES]
    # Optional, user-approved public RSS feeds. Generic feed URLs do not prove location.
    for i, feed in enumerate(os.getenv('EXTRA_RSS_FEEDS', '').split(','), 1):
        feed = feed.strip()
        if feed.startswith('https://'):
            queries.append((f'Approved RSS {i}', feed, True))
    seen = load_seen()
    old_records = {}
    try:
        previous = json.loads(JSON_OUT.read_text(encoding='utf-8'))
        old_records = {x['url']: x for x in previous.get('opportunities', [])
                       if isinstance(x, dict) and x.get('url')}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    accepted = {}
    rejected = collections.Counter()
    samples = []
    feed_stats = []
    total = 0
    for source, url, approved in queries:
        checked = 0
        matched = 0
        error = ''
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'WillieBuyerRadar/5.3 (+public RSS reader)',
                'Accept': 'application/rss+xml,application/atom+xml,application/xml,text/xml'})
            with urllib.request.urlopen(req, timeout=15) as response:
                raw = response.read(1_000_000)
            for title, link, summary, date in parse_feed(raw):
                checked += 1
                total += 1
                title = clean(title)
                summary = clean(summary)
                parsed = urllib.parse.urlparse(link)
                reasons = []
                if parsed.scheme not in ('http', 'https') or not parsed.netloc:
                    reasons.append('invalid public source URL')
                elif blocked_domain(link):
                    reasons.append('irrelevant reference/entertainment website')
                pub = parse_date(date)
                score, locs, content_reasons, inferred_location, priority = assess(title, summary, pub, now, min_score, max_age, link)
                # A community-based location is explicitly marked for verification.
                reasons.extend(content_reasons)
                if reasons:
                    for reason in set(reasons):
                        rejected[reason] += 1
                    if len(samples) < 60:
                        samples.append({'title': title[:180], 'reasons': reasons, 'source': source})
                    continue
                matched += 1
                identifier = hashlib.sha256(link.encode('utf-8')).hexdigest()[:20]
                first_seen = seen.get(identifier) or old_records.get(link, {}).get('first_seen_utc') or timestamp
                record = {'first_seen_utc': first_seen, 'published_utc': pub.isoformat() if pub else '',
                          'source': source, 'title': title[:250], 'url': link,
                          'summary': summary[:500], 'locations': locs, 'score': score,
                          'priority': priority,
                          'new_this_run': identifier not in seen}
                if link not in accepted or accepted[link]['score'] < score:
                    accepted[link] = record
                seen[identifier] = first_seen
        except Exception as exc:
            error = f'{type(exc).__name__}: {str(exc)[:150]}'
        feed_stats.append({'source': source, 'items': checked, 'matches': matched, 'error': error})
    retained = 0
    for url, rec in old_records.items():
        if url in accepted:
            continue
        published = parse_date(rec.get('published_utc', ''))
        score, locs, reasons, inferred, priority = assess(
            rec.get('title', ''), rec.get('summary', ''), published, now,
            min_score, max_age, url)
        if reasons:
            continue
        saved = dict(rec)
        saved.update(score=score, locations=locs, priority=priority,
                     new_this_run=False)
        accepted[url] = saved
        retained += 1
    rows = sorted(accepted.values(), key=lambda x: (x['score'], x['first_seen_utc']), reverse=True)[:200]
    data = {'version': '5.3', 'last_scan_utc': timestamp, 'status': 'completed',
            'stats': {'sources_checked': len(queries),
                      'sources_accessible': sum(not x['error'] for x in feed_stats),
                      'items_checked': total,
                      'matches_this_scan': sum(x['matches'] for x in feed_stats),
                      'new_this_scan': sum(x['new_this_run'] for x in rows),
                      'dashboard_opportunities': len(rows),
                      'retained_from_prior_scans': retained},
            'rejection_reasons': dict(rejected.most_common()),
            'feed_stats': feed_stats, 'rejection_samples': samples,
            'opportunities': rows,
            'disclaimer': 'Unverified recent public RSS posts, not confirmed buyers. Verify original post, age, intent and location. No private contact data collected.'}
    JSON_OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    STATE.write_text(json.dumps(seen, indent=2) + '\n', encoding='utf-8')
    with CSV_OUT.open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, 'locations': ', '.join(row['locations'])})
    lines = [f'Willie Buyer Radar 5.3 — {timestamp}',
             f'Checked {total} results across {len(queries)} feeds; matched {data["stats"]["matches_this_scan"]}; dashboard has {len(rows)} opportunities.',
             '', 'REJECTION REASONS (an item may have multiple):']
    lines += [f'{k}: {v}' for k, v in rejected.most_common()]
    lines += ['', 'FEED RESULTS:']
    lines += [f'{f["source"]}: {f["items"]} items, {f["matches"]} matches' +
              (f', ERROR {f["error"]}' if f['error'] else '') for f in feed_stats]
    lines += ['', 'SAMPLE REJECTIONS:']
    lines += [f'- {s["title"]} | {"; ".join(s["reasons"])}' for s in samples]
    lines += ['', 'Public RSS only. Search engines may not index buyer posts. Matches are unverified.']
    DIAG_OUT.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'Radar 5.3: {total} checked, {data["stats"]["matches_this_scan"]} matched, {len(rows)} displayed')

if __name__ == '__main__':
    main()
