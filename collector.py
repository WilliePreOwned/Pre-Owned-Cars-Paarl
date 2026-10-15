"""Public search discovery: RSS search snippets, not verified individual buyers."""
import json, re, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
QUERIES=[
 '"looking to buy" "car" "Cape Town"',
 '"looking for" "bakkie" "Western Cape"',
 '"wanted" "vehicle" "Paarl"',
 '"looking for a car" "Stellenbosch"',
 '"want to buy" "used car" "Cape Town"',
 'site:junkmail.co.za/cars/wanted "Western Cape"',
]
HEADERS={'User-Agent':'Mozilla/5.0 (compatible; PublicLeadDiscovery/1.0)'}
path=Path(__file__).with_name('discoveries.json')
try: old=json.loads(path.read_text(encoding='utf8'))
except (OSError,ValueError): old=[]
items={i['url']:i for i in old if isinstance(i,dict) and i.get('url')}
for q in QUERIES:
    url='https://www.google.com/search?'+urllib.parse.urlencode({'q':q,'tbm':'nws'})
    feed='https://news.google.com/rss/search?'+urllib.parse.urlencode({'q':q,'hl':'en-ZA','gl':'ZA','ceid':'ZA:en'})
    try:
        req=urllib.request.Request(feed,headers=HEADERS)
        with urllib.request.urlopen(req,timeout=15) as response: xml=response.read(500000)
        root=ET.fromstring(xml)
        for entry in root.findall('.//item')[:12]:
            title=(entry.findtext('title') or '').strip()
            link=(entry.findtext('link') or '').strip()
            if not title or not link: continue
            # Do not store people's names, phone numbers, or emails from snippets.
            if re.search(r'\b(sale|dealership|review|launch|price list)\b',title,re.I): continue
            items[link]={'title':title[:180],'url':link,'query':q,'found_at':datetime.now(timezone.utc).isoformat(),'type':'unverified public result'}
    except Exception as e: print('Search unavailable:',q,str(e)[:100])
path.write_text(json.dumps(list(items.values())[-300:],ensure_ascii=False,indent=2),encoding='utf8')
print('Saved',len(items),'unverified search results')
