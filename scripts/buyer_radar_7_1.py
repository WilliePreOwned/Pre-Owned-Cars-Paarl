#!/usr/bin/env python3
"""Buyer Radar 7.1: public RSS discovery; Python standard library only."""
import collections, csv, datetime as dt, email.utils, hashlib, html, json, os, re, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
NOW=dt.datetime.now(dt.timezone.utc)
DAYS=int(os.getenv('RADAR_DAYS','7'))
QUERIES=[
 '"looking for" "car" "Cape Town"', '"looking to buy" "bakkie" "Western Cape"',
 '"need a car" "Paarl"', '"want to buy" "Hilux" "Cape Town"',
 '"looking for" "Ranger" "Western Cape"', '"looking for" "Polo" "Cape Town"',
 '"looking for" "Swift" "Western Cape"', '"looking for" "NP200" "Cape Town"',
 '"need a double cab" "Western Cape"', '"car under R150000" "Cape Town"',
 '"op soek na" "motor" "Paarl"', '"ek soek" "bakkie" "Kaap"',
 '"wil koop" "motor" "Wes-Kaap"', '"soek ' + 'n kar" "Stellenbosch"',
 '"looking for" "SUV" "Somerset West"', '"looking for" "car" "Wellington"',
 '"looking for" "car" "George"', '"looking for" "car" "Worcester"',
 '"want to buy" "used car" "Cape Town"', '"looking for" "new car" "Western Cape"',
 '"looking for" "car" "Franschhoek"', '"op soek na" "voertuig" "Kaapstad"',
 '"need a car" "Malmesbury"', '"looking for" "car" "Hermanus"'
]
PLACES=['paarl','cape town','western cape','stellenbosch','wellington','franschhoek','somerset west','strand','bellville','durbanville','brackenfell','kuils river','worcester','malmesbury','george','hermanus','kaapstad','wes-kaap','kaap','boland','winelands','swartland','overberg']
BUY=[r'\blooking for\b',r'\blooking to buy\b',r'\bwant to buy\b',r'\bneed (?:a|an)\b',r'\bsearching for\b',r'\bop soek na\b',r'\bek soek\b',r'\bwil koop\b',r'\bbenodig\b']
VEH=['car','vehicle','bakkie','suv','double cab','pickup','motor','kar','voertuig','hilux','ranger','polo','swift','np200','corolla','fortuner','duster','picanto','i10','kwid','t-cross','tiggo','jetour','haval']
SELL=[r'\bfor sale\b',r'\bte koop\b',r'\bwe sell\b',r'\bdealership\b',r'\bstock available\b',r'\bfinance available\b',r'\bcontact our sales\b',r'\bapply now\b']
def clean(s): return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',s or ''))).strip()
def dateparse(s):
 try:
  x=email.utils.parsedate_to_datetime(s)
  return x.astimezone(dt.timezone.utc) if x.tzinfo else x.replace(tzinfo=dt.timezone.utc)
 except (ValueError,TypeError,IndexError,OverflowError): return None
def original_url(u):
 try:
  q=urllib.parse.parse_qs(urllib.parse.urlparse(u).query)
  return q.get('url',[u])[0] if 'bing.com' in urllib.parse.urlparse(u).netloc else u
 except ValueError: return u
def classify(item):
 t=(item['title']+' '+item['description']).lower(); reasons=[]; score=0
 when=dateparse(item['published'])
 if not when: reasons.append('missing_date')
 elif when>NOW+dt.timedelta(hours=12): reasons.append('future_date')
 elif NOW-when>dt.timedelta(days=DAYS): reasons.append('older_than_7_days')
 else: score+=15
 if not any(re.search(x,t) for x in BUY): reasons.append('no_explicit_buyer_intent')
 else: score+=40
 if not any(v in t for v in VEH): reasons.append('no_vehicle_match')
 else: score+=15
 if not any(place in t for place in PLACES): reasons.append('location_unverified')
 else: score+=20
 if any(re.search(x,t) for x in SELL): reasons.append('seller_or_dealer_language')
 else: score+=10
 if re.search(r'\b(?:r\s?\d[\d ,.]*(?:k)?|budget|begroting|onder r|under r)\b',t): score+=5
 # Hard rejections avoid misleading buyer claims. Location uncertainty is reviewable.
 hard={'missing_date','future_date','older_than_7_days','no_explicit_buyer_intent','no_vehicle_match','seller_or_dealer_language'}
 status='rejected' if any(x in hard for x in reasons) else ('qualified' if 'location_unverified' not in reasons and score>=80 else 'review')
 return score,status,reasons

def feeds(q):
 params=urllib.parse.urlencode({'q':q,'hl':'en-ZA','gl':'ZA','ceid':'ZA:en'})
 yield 'google_news','https://news.google.com/rss/search?'+params
 params=urllib.parse.urlencode({'q':q,'format':'rss'})
 yield 'bing_news','https://www.bing.com/news/search?'+params

def fetch(url):
 req=urllib.request.Request(url,headers={'User-Agent':'BuyerRadar/7.1 (+public RSS; no login)'})
 with urllib.request.urlopen(req,timeout=15) as r: data=r.read(1_500_000)
 root=ET.fromstring(data)
 for x in root.findall('.//item'):
  def val(tag): return clean(x.findtext(tag) or '')
  yield {'title':val('title'),'description':val('description'),'url':original_url(val('link')),'published':val('pubDate')}

def main():
 counts=collections.Counter(); errors=[]; records={}; sources=collections.Counter()
 for q in QUERIES:
  for source,url in feeds(q):
   counts['feeds_attempted']+=1
   try:
    for item in fetch(url):
     counts['entries_seen']+=1; sources[source]+=1
     if not item['url'] or not item['title']:
      counts['missing_url_or_title']+=1;continue
     key=hashlib.sha256(item['url'].encode()).hexdigest()[:16]
     if key in records:
      counts['duplicate']+=1;continue
     item.update({'id':key,'source':source,'query':q})
     item['score'],item['status'],item['reasons']=classify(item)
     records[key]=item;counts[item['status']]+=1
     for reason in item['reasons']: counts['reason_'+reason]+=1
   except Exception as e:
    counts['feed_errors']+=1; errors.append({'source':source,'query':q,'error':str(e)[:180]})
 rows=sorted(records.values(),key=lambda r:(r['status']=='qualified',r['score'],r['published']),reverse=True)
 data={'version':'7.1','generated_at':NOW.isoformat(),'window_days':DAYS,'summary':dict(counts),'opportunities':[r for r in rows if r['status'] in ('qualified','review')]}
 (ROOT/'buyer-radar-7-1.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
 with (ROOT/'buyer-radar-7-1.csv').open('w',newline='',encoding='utf-8-sig') as f:
  w=csv.DictWriter(f,fieldnames=['status','score','published','title','description','url','source','query','reasons'])
  w.writeheader()
  for r in data['opportunities']: w.writerow({k:'; '.join(r[k]) if k=='reasons' else r.get(k,'') for k in w.fieldnames})
 report={'generated_at':NOW.isoformat(),'queries':len(QUERIES),'counts':dict(counts),'source_entries':dict(sources),'errors':errors[:100], 'rejected_samples':[{'title':r['title'],'reasons':r['reasons'],'url':r['url']} for r in rows if r['status']=='rejected'][:40]}
 (ROOT/'buyer-radar-7-1-diagnostics.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'summary':dict(counts),'errors':len(errors)},indent=2))
if __name__=='__main__': main()
