#!/usr/bin/env python3
"""Willie Buyer Radar 7.3. Public RSS only; no private profiles or contact harvesting."""
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
FIELDS = ['first_seen_utc','published_utc','source','title','url','summary','locations','score','priority','new_this_run']

# Search engines are discovery aids, not proof of a buyer. The title must be an actual vehicle request.
# Wider coverage of *public indexed discussions*, not advertisements or private groups.
# Search results are only leads when the original post passes strict title, date and area checks.
SEARCHES = [
    'site:reddit.com/r/capetown/ "looking to buy" "car"',
    'site:reddit.com/r/capetown/ "buying a used car"',
    'site:reddit.com/r/capetown/ "first car" "buy"',
    'site:reddit.com/r/askSouthAfrica/ "buy a car" "Cape Town"',
    'site:mybroadband.co.za/forum/ "buying a car" "Cape Town"',
    'site:4x4community.co.za/forum/ "looking for" "bakkie"',
    '"looking to buy a car" "Cape Town" site:reddit.com',
    '"looking to buy a bakkie" "Western Cape" site:reddit.com',
    '"looking for a used car" "Paarl" site:reddit.com',
    '"buying my first car" "Cape Town" site:reddit.com',
    '"soek n bakkie" "Wes-Kaap" site:reddit.com',
    '"op soek na" "kar" "Kaapstad" site:reddit.com',
]
# Only these public discussion communities are candidates. Bing often ignores
# query site restrictions and returns US retailers, shopping and spam sites.
ALLOWED_DISCUSSION_HOSTS = ('reddit.com', 'mybroadband.co.za', '4x4community.co.za')
FOREIGN_PLACE = re.compile(r'\b(?:Renton|Seattle|Washington State|California|Texas|United States|\bUSA\b|\bUK\b)\b', re.I)

LOCATIONS = ['western cape','cape town','paarl','stellenbosch','bellville','durbanville','somerset west',
             'brackenfell','kuils river','wellington','strand','goodwood','milnerton','malmesbury',
             'franschhoek','george','table view','cape winelands','kaapstad','wes-kaap','parow',
             'kraaifontein','claremont','mitchells plain','muizenberg','blouberg','hermanus',
             'oudtshoorn','knysna','mossel bay','vredenburg','saldanha','langebaan','worcester','ceres','fish hoek','hout bay','constantia','gordon’s bay','gordons bay','observatory','sea point','northern suburbs','southern suburbs']
VEHICLE = r'(?:car|cars|vehicle|vehicles|bakkie|bakkies|pickup|suv|hatchback|sedan|4x4|hilux|ranger|polo|corolla|fortuner|double[ -]?cab|kar|voertuig|motor|np200|swift|picanto)'
# Match purchase intent in a single coherent phrase. No 'buy food' + 'car' false positives.
BUYER_TITLE = re.compile(
    rf'\b(?:looking\s+(?:to\s+buy|for)|want(?:ing)?\s+to\s+buy|need(?:ing)?|searching\s+for|seeking)\s+(?:(?:a|an|my|the|used|new|second[ -]?hand|reliable|affordable|cheap|first)\s+){{0,5}}{VEHICLE}\b'
    rf'|\b(?:buy|buying|purchase|purchasing)\s+(?:(?:a|an|my|the|used|new|second[ -]?hand|reliable|affordable|first)\s+){{0,5}}{VEHICLE}\b'
    rf'|\b{VEHICLE}\s+(?:wanted|to\s+buy|for\s+purchase)\b'
    rf'|\b(?:what|which)\s+{VEHICLE}\s+should\s+i\s+buy\b'
    rf'|\b(?:help\s+with|advice\s+on)\s+buying\s+(?:(?:a|an|used|second[ -]?hand)\s+){{0,3}}{VEHICLE}\b'
    rf'|\b(?:my\s+first|first)\s+{VEHICLE}\s*[-:]?\s*(?:what\s+should\s+i\s+buy|recommendations|advice)\b'
    rf'|\b(?:recommend|suggest)\s+(?:me\s+)?(?:(?:a|an|used|reliable|affordable)\s+){{0,3}}{VEHICLE}\b'
    rf'|\b(?:where\s+can\s+i\s+find)\s+(?:(?:a|an|used|second[ -]?hand)\s+){{0,3}}{VEHICLE}\s+(?:to\s+buy|for\s+sale)\b'
    rf'|\b(?:soek\s+(?:\x27n|n|vir)|op\s+soek\s+na)\s+(?:(?:\x27n|n|\w+)\s+){{0,3}}{VEHICLE}\b'
    rf'|\b(?:waar\s+kan\s+ek|ek\s+wil)\s+(?:(?:\x27n|n|\w+)\s+){{0,4}}{VEHICLE}\s+koop\b', re.I)
# A few highly relevant questions can be accepted, but only when explicitly vehicle-specific.
BUYER_QUESTION = re.compile(rf'\b(?:where\s+(?:can|should)\s+i\s+buy|anyone\s+selling)\s+(?:(?:a|an|used|second[ -]?hand)\s+){{0,3}}{VEHICLE}\b', re.I)
SELLER = re.compile(r'\b(?:for sale|selling my|we sell|our stock|stock available|dealership|dealer special|apply for finance|book a test drive|browse our stock|cars for sale|vehicles for sale|buying guide|how to buy)\b', re.I)
UNRELATED = re.compile(r'\b(?:buy food|beggars|takeaway restaurants|rental apartment|rent a car|car rental|mechanic wanted|looking for a mechanic|looking for a job|cost of living|salary|buy a house)\b', re.I)
BUDGET = re.compile(r'\b(?:budget|under|below|up to|maximum|afford|r\s?\d[\d, ]{3,}|\d{2,3}k)\b', re.I)
URGENT = re.compile(r'\b(?:urgent|asap|this week|this month|ready to buy|cash buyer)\b', re.I)
BLOCKED = ('wikipedia.org','wiktionary.org','merriam-webster.com','dictionary.com','imdb.com',
           'thesaurus.com','thefreedictionary.com','britannica.com','tvguide.com','rottentomatoes.com')

def clean(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', value or ''))).strip()

def parse_date(value):
    if not value:
        return None
    try:
        d = dt.datetime.fromisoformat(value.strip().replace('Z','+00:00'))
    except (TypeError,ValueError):
        try:
            d = email.utils.parsedate_to_datetime(value)
        except (TypeError,ValueError,OverflowError):
            return None
    if d is None:
        return None
    return d.replace(tzinfo=UTC) if d.tzinfo is None else d.astimezone(UTC)

def parse_feed(raw):
    root = ET.fromstring(raw)
    for item in root.findall('.//item'):
        def get(tag):
            n = item.find(tag)
            return ''.join(n.itertext()).strip() if n is not None else ''
        yield get('title'),get('link'),get('description'),get('pubDate')
    ns = {'a':'http://www.w3.org/2005/Atom'}
    for item in root.findall('.//a:entry',ns):
        link = next((x.get('href','') for x in item.findall('a:link',ns)
                     if x.get('rel','alternate') == 'alternate'),'')
        yield item.findtext('a:title','',ns),link,(item.findtext('a:summary','',ns) or item.findtext('a:content','',ns)),(item.findtext('a:published','',ns) or item.findtext('a:updated','',ns))

def assess(title,summary,published,now,url='',max_age=30):
    title,summary = clean(title),clean(summary)
    text = title+' '+summary
    locs = sorted(x for x in LOCATIONS if re.search(r'(?<!\w)'+re.escape(x)+r'(?!\w)',text,re.I))
    parsed = urllib.parse.urlparse(url)
    is_cpt = (parsed.hostname or '').lower() in ('reddit.com','www.reddit.com') and parsed.path.lower().startswith('/r/capetown/')
    request = bool(BUYER_TITLE.search(title) or BUYER_QUESTION.search(title))
    # Explicit buying-advice questions, without matching unrelated 'buy' mentions.
    request = request or bool(re.search(
        rf'\b(?:help|advice|tips|recommendations?)\s+(?:me\s+)?(?:with|on|for|about)\s+'
        rf'(?:buying|purchasing)\s+(?:(?:a|an|the|used|second[ -]?hand|first)\s+){{0,4}}{VEHICLE}\b',
        title, re.I))
    # 'Buying a used car in Cape Town?' is a genuine first-person discussion topic.
    request = request or bool(re.search(
        rf'^\s*buying\s+(?:(?:a|an|the|used|second[ -]?hand|first)\s+){{0,4}}{VEHICLE}\b',
        title, re.I))
    if not locs and is_cpt and request:
        locs = ['cape town (community; verify location)']
    reasons=[]
    if not request: reasons.append('title does not clearly request buying a vehicle')
    # Domain gate comes before considering anything a lead. Search engines may
    # return irrelevant domains even for site:reddit.com searches.
    host=(parsed.hostname or '').lower()
    if not any(host == d or host.endswith('.'+d) for d in ALLOWED_DISCUSSION_HOSTS):
        reasons.append('outside approved public discussion sources')
    if FOREIGN_PLACE.search(title):
        reasons.append('foreign location in title')
    if not locs: reasons.append('no Western Cape location in result text')
    if SELLER.search(title): reasons.append('seller/advertisement title')
    if re.search(r'\b(?:looking for|need|want)\s+(?:a\s+)?(?:driver|mechanic|car wash|car parts|car seat|car insurance|car loan)\b',title,re.I): reasons.append('not a vehicle purchase')
    if UNRELATED.search(title): reasons.append('unrelated subject in title')
    if published is None: reasons.append('publication date unavailable')
    elif published > now+dt.timedelta(days=1): reasons.append('publication date in future')
    elif now-published > dt.timedelta(days=max_age): reasons.append('older than age limit')
    host=(parsed.hostname or '').lower()
    if parsed.scheme not in ('https','http') or not host: reasons.append('invalid public source URL')
    if any(host==d or host.endswith('.'+d) for d in BLOCKED): reasons.append('irrelevant reference/entertainment website')
    score=min(100,65*request+20*bool(locs)+10*bool(BUDGET.search(text))+5*bool(URGENT.search(text)))
    priority='Review' if is_cpt or BUYER_QUESTION.search(title) else ('High' if score>=85 else 'Review')
    return score,locs,reasons,priority

def read_json(path,default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):
        return default

def main():
    now=dt.datetime.now(UTC)
    stamp=now.isoformat(timespec='seconds')
    max_age=int(os.getenv('MAX_POST_AGE_DAYS','30'))
    # Direct public discussion search feeds first. These can return HTTP 403/429;
    # a failed feed is logged, never treated as zero confirmed buyers.
    direct_terms = ['buy car', 'buying car', 'second hand car', 'looking for bakkie']
    queries = []
    for community in ():
        for term in direct_terms:
            params = urllib.parse.urlencode({'q':term,'restrict_sr':'1','sort':'new','t':'month','limit':'50'})
            queries.append((f'Reddit direct r/{community}: {term}',
                            f'https://www.reddit.com/r/{community}/search.rss?{params}'))
    # Bing is supplemental, limited to targeted queries to avoid dictionary/US retail noise.
    for q in SEARCHES:
        queries.append(('Bing RSS: '+q,
                        'https://www.bing.com/search?format=rss&q='+urllib.parse.quote(q)))
    # Optional user-approved public RSS feeds from the GitHub Actions environment.
    for i,url in enumerate(os.getenv('EXTRA_RSS_FEEDS','').split(','),1):
        url=url.strip()
        parsed=urllib.parse.urlparse(url)
        if parsed.scheme == 'https' and parsed.hostname:
            queries.append((f'Approved RSS {i}',url))
    # Do not scan the same feed twice when a user-configured feed overlaps.
    queries=list(dict((url,(name,url)) for name,url in queries).values())
    seen=read_json(STATE,{})
    if not isinstance(seen,dict): seen={}
    previous=read_json(JSON_OUT,{})
    previous_rows={x['url']:x for x in previous.get('opportunities',[]) if isinstance(x,dict) and x.get('url')}
    accepted={}
    rejected=collections.Counter()
    samples=[]
    candidate_samples=[]
    seen_candidate_urls=set()
    feed_stats=[]
    checked_total=0
    for source,feed in queries:
        checked=matched=0
        error=''
        try:
            req=urllib.request.Request(feed,headers={'User-Agent':'Mozilla/5.0 (compatible; WillieBuyerRadar/7.3; public RSS reader)', 'Accept':'application/rss+xml,application/atom+xml,application/xml,text/xml'})
            with urllib.request.urlopen(req,timeout=8) as response:
                raw=response.read(1_000_000)
            for title,url,summary,date in parse_feed(raw):
                checked+=1
                checked_total+=1
                pub=parse_date(date)
                score,locs,reasons,priority=assess(title,summary,pub,now,url,max_age)
                # Keep relevant public-discussion candidates in diagnostics, including
                # those rejected on date/location, so we can improve source quality.
                host=(urllib.parse.urlparse(url).hostname or '').lower()
                is_discussion=any(host==d or host.endswith('.'+d) for d in ALLOWED_DISCUSSION_HOSTS)
                if is_discussion and url not in seen_candidate_urls and len(candidate_samples)<40:
                    candidate_samples.append({'title':clean(title)[:180], 'url':url,
                                              'reasons':reasons, 'source':source})
                    seen_candidate_urls.add(url)
                if reasons:
                    rejected.update(set(reasons))
                    if len(samples)<50: samples.append({'title':clean(title)[:180],'reasons':reasons,'source':source})
                    continue
                matched+=1
                ident=hashlib.sha256(url.encode()).hexdigest()[:20]
                first=seen.get(ident) or previous_rows.get(url,{}).get('first_seen_utc') or stamp
                rec={'first_seen_utc':first,'published_utc':pub.isoformat(),'source':source,
                     'title':clean(title)[:250],'url':url,'summary':clean(summary)[:500],
                     'locations':locs,'score':score,'priority':priority,'new_this_run':ident not in seen}
                if url not in accepted or accepted[url]['score']<score: accepted[url]=rec
                seen[ident]=first
        except Exception as exc:
            error=f'{type(exc).__name__}: {str(exc)[:150]}'
        feed_stats.append({'source':source,'items':checked,'matches':matched,'error':error})
    retained=0
    for url,rec in previous_rows.items():
        if url in accepted: continue
        score,locs,reasons,priority=assess(rec.get('title',''),rec.get('summary',''),parse_date(rec.get('published_utc','')),now,url,max_age)
        if reasons: continue
        saved=dict(rec)
        saved.update(score=score,locations=locs,priority=priority,new_this_run=False)
        accepted[url]=saved
        retained+=1
    rows=sorted(accepted.values(),key=lambda x:(x['score'],x['first_seen_utc']),reverse=True)[:200]
    direct_failures=sum(bool(f['error']) for f in feed_stats if f['source'].startswith('Reddit direct'))
    data={'version':'7.3','last_scan_utc':stamp,'status':'completed',
          'stats':{'sources_checked':len(queries),'sources_accessible':sum(not x['error'] for x in feed_stats),
                   'items_checked':checked_total,'matches_this_scan':sum(x['matches'] for x in feed_stats),
                   'new_this_scan':sum(x['new_this_run'] for x in rows),
                   'dashboard_opportunities':len(rows),'retained_from_prior_scans':retained,'direct_feed_failures':direct_failures},
          'rejection_reasons':dict(rejected.most_common()),'feed_stats':feed_stats,
          'rejection_samples':samples,'candidate_samples':candidate_samples,'opportunities':rows,
          'disclaimer':'Unverified public RSS results, not confirmed buyers. Verify post date, intent, location and platform rules. No private contact data collected.'}
    JSON_OUT.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    STATE.write_text(json.dumps(seen,indent=2)+'\n',encoding='utf-8')
    with CSV_OUT.open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS)
        writer.writeheader()
        for rec in rows: writer.writerow({**rec,'locations':', '.join(rec['locations'])})
    lines=[f'Willie Buyer Radar 7.3 — {stamp}',f'Checked {checked_total} results across {len(queries)} feeds; matched {data["stats"]["matches_this_scan"]}; dashboard has {len(rows)} opportunities.', '', 'REJECTION REASONS:']
    lines += [f'{k}: {v}' for k,v in rejected.most_common()]
    lines += ['', f'DIRECT FEED FAILURES: {direct_failures} (HTTP 403/429 may indicate access restrictions; do not bypass)', 'FEED RESULTS:']+[f'{f["source"]}: {f["items"]} items, {f["matches"]} matches'+(f', ERROR {f["error"]}' if f['error'] else '') for f in feed_stats]
    lines += ['', 'DISCUSSION SOURCE CANDIDATES (review relevance and reasons):']
    lines += [f'- {s["title"]} | {s["url"]} | {"; ".join(s["reasons"]) or "ACCEPTED"}' for s in candidate_samples]
    lines += ['', 'SAMPLE REJECTIONS:']+[f'- {s["title"]} | {"; ".join(s["reasons"])}' for s in samples]
    DIAG_OUT.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(f'Radar 7.3: {checked_total} checked, {data["stats"]["matches_this_scan"]} matched, {len(rows)} displayed; {direct_failures} direct feeds unavailable')

if __name__=='__main__':
    main()
