#!/usr/bin/env python3
"""Send Willie Buyer Radar email alerts via SMTP; no third-party dependencies."""
import csv
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlparse

CSV = Path('buyer_opportunities_v3.csv')

def main():
    test = os.getenv('SEND_TEST_EMAIL', 'false').lower() == 'true'
    recipient = os.getenv('ALERT_TO', '').strip()
    sender = os.getenv('SMTP_USER', '').strip()
    password = os.getenv('SMTP_PASSWORD', '')
    host = os.getenv('SMTP_HOST', '').strip()
    port = int(os.getenv('SMTP_PORT', '465'))
    if not all((recipient, sender, password, host)):
        print('SMTP not configured: set ALERT_TO, SMTP_HOST, SMTP_USER, SMTP_PASSWORD. Skipping.')
        return
    if port not in (465, 587):
        raise ValueError('SMTP_PORT must be 465 (SSL) or 587 (STARTTLS)')
    rows = []
    if not test:
        if not CSV.exists():
            print('No CSV output found; skipping alerts.')
            return
        with CSV.open(encoding='utf-8-sig', newline='') as fh:
            rows = [r for r in csv.DictReader(fh) if r.get('new_this_run', '').lower() == 'yes']
        if not rows:
            print('No new opportunities; no email sent.')
            return
    message = EmailMessage()
    message['From'] = sender
    message['To'] = recipient
    message['Subject'] = ('Willie Buyer Radar - test email' if test else f'Willie Buyer Radar - {len(rows)} new possible buyer request(s)')
    if test:
        body = 'Your Willie Buyer Radar SMTP settings are working. This is a test email, not a real buyer lead.'
    else:
        lines = [f'{len(rows)} NEW PUBLIC SEARCH MATCH(ES) — UNVERIFIED',
                 'Review the original posts before contacting anyone. Do not treat search snippets as verified buyer enquiries.', '']
        for i, r in enumerate(rows[:20], 1):
            link = r.get('url', '')
            if urlparse(link).scheme not in ('https', 'http'):
                link = '(invalid link)'
            lines.extend([f'{i}. {r.get("title", "")[:200]}',
                          f'Score: {r.get("score", "?")} | Location: {r.get("location_match", "unknown")}',
                          f'Source: {r.get("source", "unknown")}', f'Original link: {link}',
                          f'Summary: {r.get("summary", "")[:300]}', ''])
        if len(rows) > 20:
            lines.append(f'{len(rows)-20} additional matches are in the GitHub Actions CSV artifact.')
        body = '\n'.join(lines)
    message.set_content(body)
    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=25, context=context) as smtp:
            smtp.login(sender, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=25) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(sender, password)
            smtp.send_message(message)
    print(f'Email delivered to SMTP server for {recipient} ({"test" if test else str(len(rows)) + " matches"}).')

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Email notification failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        raise SystemExit(1)
