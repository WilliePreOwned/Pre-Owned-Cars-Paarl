#!/usr/bin/env python3
"""Publish due, explicitly approved Facebook Page posts from a JSON queue."""
import datetime as dt
import json
import os
import pathlib
import urllib.parse
import urllib.request
import urllib.error

ROOT = pathlib.Path(__file__).resolve().parents[1]
QUEUE = ROOT / 'facebook-approved-queue.json'
API = os.environ.get('META_GRAPH_VERSION', 'v26.0')

def main():
    items = json.loads(QUEUE.read_text(encoding='utf-8'))
    now = dt.datetime.now(dt.timezone.utc)
    token = os.getenv('FB_PAGE_ACCESS_TOKEN', '')
    page = os.getenv('FB_PAGE_ID', '')
    enabled = os.getenv('FB_PUBLISH_ENABLED', 'false').lower() == 'true'
    changed = False
    for item in items:
        if item.get('status') != 'approved' or item.get('approved_for_facebook') is not True:
            continue
        due = dt.datetime.fromisoformat(item['scheduled_at'].replace('Z', '+00:00'))
        if due.tzinfo is None:
            raise ValueError('scheduled_at must include a timezone offset')
        if due > now:
            continue
        print('Due approved item:', item['id'])
        if not enabled:
            print('DRY RUN: publishing disabled')
            continue
        if not token or not page:
            raise RuntimeError('FB_PAGE_ACCESS_TOKEN and FB_PAGE_ID secrets required')
        photo = item.get('photo_url', '').strip()
        if photo and not photo.startswith('https://'):
            raise ValueError('photo_url must use HTTPS')
        endpoint = 'photos' if photo else 'feed'
        data = {'access_token': token}
        if photo:
            data.update(url=photo, caption=item['message'])
        else:
            data['message'] = item['message']
        request = urllib.request.Request('https://graph.facebook.com/' + API + '/' + urllib.parse.quote(page, safe='') + '/' + endpoint, data=urllib.parse.urlencode(data).encode(), method='POST')
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            print('Facebook API error (credentials omitted):', exc.code, exc.reason)
            raise
        item['status'] = 'published'
        item['facebook_post_id'] = result.get('post_id') or result.get('id')
        item['published_at'] = now.isoformat()
        changed = True
        print('Published item:', item['id'])
        # Save immediately to reduce duplicate posts after later failures.
        QUEUE.write_text(json.dumps(items, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    if not changed:
        print('No posts published.')

if __name__ == '__main__':
    main()
