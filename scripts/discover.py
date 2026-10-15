#!/usr/bin/env python3
"""Public RSS search, with strict buyer-intent filtering and no personal-data scraping."""
import csv, datetime as dt, email.utils, html, os, re, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from pathlib import Path

OUT = Path('buyer_opportunities.csv')
QUERIES = [
    '"wanted to buy" "car" "Western Cape"',
    '"looking to buy" "bakkie" "Cape Town"',
    '"looking for a car" "Paarl"',
    '"wanted" "used car" "Stellenbosch"',
    '"looking to buy" "vehicle" "Cape Town"',
    '"wanted" "bakkie" "Western Cape"',
]
BUYER = re.compile(r'\b(wanted to buy|want to buy|looking to buy|looking for (?:a|an|used|second.hand)|vehicle wanted|car wanted|bakkie wanted|seeking (?:a|an))\b', re.I)
CAR = re.compile(r'\b(car|vehicle|bakkie|suv|hatchback|sedan|pickup|ford ranger|toyota hilux|vw polo)\b', re.I)
REGION = re.compile(r'\b(paarl|cape town|stellenbosch|western cape|bellville|durbanville|worcester|somerset west|brackenfell|kuils river|malmesbury)\b', re.I)
EXCLUDE = re.compile(r'\b(review|test drive|car sales rise|finance tips|how to|buying guide|best cars|new model|launch|dealership offers|advertorial|opinion|market trends|scam warning)\b', re.I)

def get_feed(q):
    params = urllib.parse.urlencode({'q': q+' when:30d', 'hl':'en-ZA', 'gl':'ZA', 'ceid':'ZA:en'})
    url = 'https://news.google.com/rss/search?'+params
    req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0 (compatible; PublicOpportunityResearch/1.0)'})
    with urllib.request.urlopen(req, timeout=25) as response:
        data=response.read(2_000_000)
    root=ET.fromstring(data)
    return root.findall('.//item')

def main():
    seen=set(); rows=[]; total=0; errors=0
    today=dt.datetime.now(dt.timezone.utc)
    for query in QUERIES:
        try: items=get_feed(query)
        except Exception as exc:
            print('Source unavailable:',query,repr(exc)); errors+=1; continue
        total+=len(items)
        for item in items:
            title=html.unescape(re.sub(r'<[^>]+>', ' ', item.findtext('title',''))).strip()
            description=html.unescape(re.sub(r'<[^>]+>', ' ', item.findtext('description',''))).strip()
            link=item.findtext('link','').strip()
            date=item.findtext('pubDate','')
            try:
                published=email.utils.parsedate_to_datetime(date).astimezone(dt.timezone.utc)
                age=(today-published).days
            except (ValueError, TypeError, AttributeError):
                continue
            if age<0 or age>30 or not link or link in seen: continue
            seen.add(link)
            # Require explicit buyer intent in headline; snippets often repeat query terms without buyer evidence.
            if not BUYER.search(title) or not CAR.search(title): continue
            if EXCLUDE.search(title): continue
            score=2
            if REGION.search(title+' '+description): score+=2
            if age<=7: score+=2
            if 'wanted' in title.lower(): score+=1
            rows.append({'priority':'HIGH' if score>=6 else 'REVIEW', 'headline':title,
                         'published_utc':published.strftime('%Y-%m-%d'), 'age_days':age,
                         'region_mentioned':'YES' if REGION.search(title+' '+description) else 'NO',
                         'source_url':link, 'matched_search':query,
                         'review_status':'UNVERIFIED — check original post before outreach'})
    rows.sort(key=lambda r:(r['priority']!='HIGH',r['age_days']))
    OUT.parent.mkdir(parents=True,exist_ok=True)
    with OUT.open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=['priority','headline','published_utc','age_days','region_mentioned','source_url','matched_search','review_status'])
        writer.writeheader();writer.writerows(rows)
    print(f'RSS entries checked: {total}; potential opportunities: {len(rows)}; feed errors: {errors}')
    print('Zero results is a valid outcome: Google News is not a classifieds buyer database.')

if __name__=='__main__': main()
