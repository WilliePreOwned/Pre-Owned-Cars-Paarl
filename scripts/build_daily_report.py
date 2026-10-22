#!/usr/bin/env python3
"""Create persistent daily public-opportunity history from existing Buyer Radar JSON."""
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'buyer-radar-data.json'
HISTORY=ROOT/'buyer-radar-history-v7.json'
CSV=ROOT/'buyer-radar-daily-v7.csv'
UTC=dt.timezone.utc

def read(path, default):
    try: return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError): return default

def normalized_url(url):
    p=urlsplit(url)
    params=[(k,v) for k,v in parse_qsl(p.query,keep_blank_values=True) if not k.lower().startswith('utm_')]
    return urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path.rstrip('/'),urlencode(params),'')).strip()

def main():
    scan=read(SOURCE,{})
    if not isinstance(scan,dict) or scan.get('status')!='completed':
        raise SystemExit('No completed buyer-radar-data.json found; run discover.py first.')
    stamp=scan.get('last_scan_utc')
    try: when=dt.datetime.fromisoformat(stamp.replace('Z','+00:00')).astimezone(UTC)
    except (ValueError,AttributeError): raise SystemExit('Missing or invalid scan timestamp')
    # Group by South African calendar day, while keeping source timestamps in UTC.
    sa=dt.timezone(dt.timedelta(hours=2))
    day=when.astimezone(sa).date().isoformat()
    hist=read(HISTORY,{})
    if not isinstance(hist,dict): hist={}
    hist.setdefault('version','7.0')
    hist.setdefault('first_recorded_date',day)
    days=hist.setdefault('days',{})
    leads=hist.setdefault('leads',{})
    scans=hist.setdefault('processed_scans',{})
    if not isinstance(days,dict) or not isinstance(leads,dict) or not isinstance(scans,dict):
        raise SystemExit('History JSON has invalid structure')
    # A repeated workflow execution for the same scanner timestamp must be idempotent.
    if stamp in scans:
        print('Scan already recorded:',stamp)
        return
    stats=scan.get('stats',{})
    new_ids=[]
    for rec in scan.get('opportunities',[]):
        if not isinstance(rec,dict) or not rec.get('url'): continue
        url=normalized_url(rec['url'])
        ident=hashlib.sha256(url.encode('utf-8')).hexdigest()[:20]
        if ident not in leads:
            leads[ident]={'id':ident,'title':str(rec.get('title',''))[:250], 'url':rec['url'],
                          'source':str(rec.get('source',''))[:200], 'published_utc':rec.get('published_utc',''),
                          'first_recorded_utc':stamp,'first_recorded_date':day,
                          'locations':rec.get('locations',[]), 'summary':str(rec.get('summary',''))[:500],
                          'score':rec.get('score',0), 'priority':rec.get('priority','Review')}
            new_ids.append(ident)
    entry=days.setdefault(day,{'scans':0,'successful_scans':0,'items_checked':0,'matches_reported':0,
                               'new_unique_leads':0,'new_lead_ids':[],'last_scan_utc':''})
    entry['scans']+=1
    entry['successful_scans']+=1
    entry['items_checked']+=int(stats.get('items_checked',0))
    entry['matches_reported']+=int(stats.get('matches_this_scan',0))
    entry['new_unique_leads']+=len(new_ids)
    entry['new_lead_ids'].extend(new_ids)
    entry['last_scan_utc']=stamp
    scans[stamp]=day
    hist['last_updated_utc']=stamp
    # Keep all leads and daily totals; prune scan keys after 400 days to avoid unbounded growth.
    cutoff=(when-dt.timedelta(days=400)).isoformat()
    hist['processed_scans']={k:v for k,v in scans.items() if k>=cutoff}
    HISTORY.write_text(json.dumps(hist,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with CSV.open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.writer(f)
        writer.writerow(['date_south_africa','successful_scans','results_checked','matches_reported_across_scans','new_unique_potential_buyers'])
        for date,record in sorted(days.items()):
            writer.writerow([date,record['successful_scans'],record['items_checked'],record['matches_reported'],record['new_unique_leads']])
    print(f'Buyer Radar 7.0: {day}, {len(new_ids)} new unique public opportunities, {len(leads)} total recorded')

if __name__=='__main__': main()
