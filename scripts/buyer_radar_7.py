#!/usr/bin/env python3
"""Buyer Radar 7: public RSS discovery only; no personal data collection."""
import csv, datetime as dt, email.utils, hashlib, html, json, re, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'buyer-radar-7.json'
CSV = ROOT / 'buyer-radar-7.csv'
DIAG = ROOT / 'buyer-radar-7-diagnostics.txt'
TOWNS = ['Paarl','Wellington','Stellenbosch','Franschhoek','Somerset West','Cape Town','Western Cape']
PHRASES = ['looking for a car', 'looking to buy a car', 'want to buy a car', 'looking for a bakkie', 'looking for a vehicle', 'car wanted', 'vehicle wanted', 'looking for a Toyota', 'looking for a Ford']
INTENT = re.compile(r'\b(looking for|looking to buy|want to buy|wanting to buy|need to buy|in search of|iso|wanted|seeking|need a|looking to purchase)\b', re.I)
VEHICLE = re.compile(r'\b(car|cars|vehicle|vehicles|bakkie|suv|sedan|hatchback|toyota|ford|vw|volkswagen|hyundai|kia|nissan|suzuki|bmw|mercedes|isuzu|hilux|ranger|polo|corolla)\b', re.I)
SELLER = re.compile(r'\b(for sale|we sell|stock available|available now|special offer|dealership|car dealer|apply for finance|buy from us)\b', re.I)
REGION = re.compile(r'\b(paarl|wellington|stellenbosch|franschhoek|somerset west|cape town|western cape|winelands)\b', re.I)
def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0 (compatible; PublicBuyerRadar/7.0)'})
    with urllib.request.urlopen(req, timeout=18) as r: return r.read(1_500_000)
def clean(value): return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', value or ''))).strip()
def parse_rss(data):
    root=ET.fromstring(data)
    for item in root.findall('.//item'):
        def val(tag): return clean(item.findtext(tag, default=''))
        yield {'title':val('title'), 'description':val('description'), 'url':val('link'), 'published':val('pubDate')}
def score(item):
    text=(item['title']+' '+item['description'])[:2500]
    if not INTENT.search(text) or not VEHICLE.search(text) or SELLER.search(item['title']): return 0
    if not REGION.search(text): return 0
    return min(100, 45 + (20 if REGION.search(item['title']) else 0) + (15 if INTENT.search(item['title']) else 0) + (10 if re.search(r'\b(R\s?\d|budget|under R|cash|finance)\b',text,re.I) else 0))
def main():
    found={}; errors=[]; queried=0; received=0
    # Public Bing RSS search; provider may block requests or return no results.
    queries=[f'"{phrase}" "{town}"' for phrase in PHRASES[:6] for town in TOWNS[:3]]
    queries += [f'"{phrase}" "{town}"' for phrase in PHRASES[6:] for town in TOWNS[3:]]
    for q in queries:
        queried+=1
        url='https://www.bing.com/search?'+urllib.parse.urlencode({'q':q,'format':'rss'})
        try:
            items=list(parse_rss(fetch(url))); received+=len(items)
            for item in items:
                s=score(item)
                if not s or not item['url'].startswith(('https://','http://')): continue
                key=hashlib.sha256(item['url'].encode()).hexdigest()[:16]
                item.update(id=key, score=s, matched_query=q, status='Unverified public request')
                if key not in found or s>found[key]['score']: found[key]=item
        except Exception as e: errors.append(f'{q}: {type(e).__name__}: {e}')
    records=sorted(found.values(),key=lambda x:-x['score'])[:150]
    payload={'generated_at':dt.datetime.now(dt.timezone.utc).isoformat(), 'total':len(records),'results':records,'sources_checked':queried,'source_items_seen':received,'errors':len(errors)}
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    with CSV.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=['title','description','url','published','score','matched_query','status']);w.writeheader();w.writerows({k:r.get(k,'') for k in w.fieldnames} for r in records)
    DIAG.write_text(f'Queries attempted: {queried}\nRSS entries seen: {received}\nQualified opportunities: {len(records)}\nErrors: {len(errors)}\n\n'+'\n'.join(errors),encoding='utf-8')
    print(f'Buyer Radar 7: {len(records)} public opportunities, {received} entries checked, {len(errors)} errors')
if __name__=='__main__': main()
