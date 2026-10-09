"""Email changes in observed asking prices between consecutive Eastern calendar days."""
import hashlib
import json
import os
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo

import pandas as pd

from tracker.band import PRICE_RANGE
from tracker.collect import read_json, write_json
from tracker.metrics import INVENTORY, canonical_runs
from tracker.storage import BAND_SCOPE, SCHOOLS, read_frames

DASHBOARD = 'https://datascience-jduyv43w9awdsp7bumizcr.streamlit.app/'
EASTERN = ZoneInfo('America/New_York')


def event_key(event, recipient):
    fields = {k: event[k] for k in ('date', 'school', 'property_id', 'before', 'after')}
    fields['recipient'] = recipient.strip().lower()
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def price_changes(db, today):
    """Require both days' reconciled searches; enrichment alone cannot create an event."""
    runs, rows = read_frames(db, 'observed')
    yesterday = (today - timedelta(days=1)).isoformat()
    current_day = today.isoformat()
    runs = runs[runs.scope.str.startswith(BAND_SCOPE + ':') &
                runs.market_date.isin([yesterday, current_day])]
    selected = canonical_runs(runs)
    changes, coverage = [], {}
    for school in SCHOOLS:
        pair = selected[selected.school.eq(school)]
        old = pair[pair.market_date.eq(yesterday)]
        new = pair[pair.market_date.eq(current_day)]
        if old.empty or new.empty:
            coverage[school] = 'waiting_for_consecutive_complete_days'
            continue
        before, after = old.iloc[0], new.iloc[0]
        if (before.scope, before.boundary_version) != (after.scope, after.boundary_version):
            coverage[school] = 'incompatible_search_scope'
            continue
        coverage[school] = 'compared'
        frame = rows[rows.run_id.isin([before.run_id, after.run_id]) &
                     rows.price.between(*PRICE_RANGE) & rows.status.isin(INVENTORY) &
                     rows.in_inventory.eq(1)].copy()
        # Search timestamps, not the later date a missing construction year was filled.
        frame['price_day'] = pd.to_datetime(frame.price_observed_at, utc=True, errors='coerce', format='mixed').dt.tz_convert(EASTERN).dt.strftime('%Y-%m-%d')
        left = frame[frame.run_id.eq(before.run_id) & frame.price_day.eq(yesterday)]
        right = frame[frame.run_id.eq(after.run_id) & frame.price_day.eq(current_day)]
        paired = left.merge(right, on='property_id', suffixes=('_before', '_after'))
        for row in paired.itertuples():
            if row.price_before == row.price_after:
                continue
            # Unknown episode IDs still support a property-level observed-price comparison.
            # An explicitly different known listing episode is a relisting, not a price edit.
            known_before = not row.episode_id_before.endswith(':unknown')
            known_after = not row.episode_id_after.endswith(':unknown')
            if known_before and known_after and row.episode_id_before != row.episode_id_after:
                continue
            delta = row.price_after - row.price_before
            changes.append(dict(date=current_day, previous_date=yesterday, school=school,
                                property_id=row.property_id, address=row.address_after,
                                before=float(row.price_before), after=float(row.price_after),
                                change=float(delta), percent=float(delta / row.price_before * 100),
                                before_observed_at=row.price_observed_at_before,
                                after_observed_at=row.price_observed_at_after,
                                source_change_date=row.price_cut_date_after if pd.notna(row.price_cut_date_after) else None,
                                url=row.url_after))
    return sorted(changes, key=lambda r: (r['change'] >= 0, -abs(r['percent']), r['property_id'])), coverage


def message_for(events, recipient, sender):
    message = EmailMessage()
    message['From'], message['To'] = sender, recipient
    message['Subject'] = f"[Schoolside] 관측 호가 변동 {len(events)}건 — {events[-1]['date']} (ET)"
    identity = hashlib.sha256('|'.join(sorted(event_key(e, recipient) for e in events)).encode()).hexdigest()
    message['Message-ID'] = f'<housing-{identity}@schoolside.local>'
    lines = ['미국 동부시간 기준 관측 호가 비교. 발송 지연 시 이전 날짜의 미발송 알림도 포함합니다.', '']
    for event in events:
        lines.extend([f"{event['previous_date']} → {event['date']}",
                      f"{event['address']} · {SCHOOLS[event['school']]}",
                      f"${event['before']:,.0f} → ${event['after']:,.0f}",
                      f"변동: {event['change']:+,.0f}달러 ({event['percent']:+.2f}%)"])
        if event.get('source_change_date'):
            lines.append(f"Zillow 표시 가격 인하일: {event['source_change_date']}")
        for label, field in [('이전 확인', 'before_observed_at'), ('현재 확인', 'after_observed_at')]:
            stamp = datetime.fromisoformat(event[field].replace('Z', '+00:00')).astimezone(EASTERN)
            lines.append(f"{label}: {stamp:%Y-%m-%d %I:%M %p %Z}")
        lines.extend([event['url'], ''])
    lines.extend([f'대시보드: {DASHBOARD}', '',
                  f'{len(SCHOOLS)}개 학군 · Houses · 침실 3+ · 욕실 2+ · $400k–$700k',
                  '두 날짜에 실제 수집한 호가의 차이입니다. 정확한 가격 변경 시각이나 거래가격을 뜻하지 않습니다.',
                  '전날 기록이 없거나 검색 수집이 불완전한 학군은 비교에서 제외합니다.'])
    message.set_content('\n'.join(lines))
    return message


class DeliveryFailure(RuntimeError):
    def __init__(self, attempts):
        self.attempts = attempts
        super().__init__('SMTP delivery failed; see sanitized stage diagnostics')


def send_message(message, username, password):
    attempts = []
    for port in (587, 465):
        smtp, stage = None, 'connect'
        try:
            if port == 587:
                smtp = smtplib.SMTP('smtp.gmail.com', port, timeout=30)
                stage = 'starttls'
                smtp.ehlo()
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            else:
                smtp = smtplib.SMTP_SSL('smtp.gmail.com', port, timeout=30, context=ssl.create_default_context())
            stage = 'authenticate'
            # Use the server's AUTH challenge instead of placing credentials in
            # the initial AUTH command; both are supported by SMTP providers.
            smtp.login(username, password.replace(' ', ''), initial_response_ok=False)
            stage = 'send'
            smtp.send_message(message)
            # A later QUIT disconnect cannot turn an accepted message into a failure.
            return
        except (OSError, smtplib.SMTPException) as exc:
            attempts.append(dict(port=port, stage=stage, error=type(exc).__name__,
                                 smtp_code=getattr(exc, 'smtp_code', None),
                                 auth_advertised=(getattr(smtp, 'esmtp_features', {}) or {}).get('auth', '')))
            if stage == 'send' or isinstance(exc, smtplib.SMTPAuthenticationError):
                break  # Do not immediately resend when acceptance is ambiguous.
        finally:
            if smtp is not None:
                try:
                    smtp.close()
                except OSError:
                    pass
    raise DeliveryFailure(attempts)


def notify(db, archive, recipient, *, dry_run=False, today=None, sender=send_message):
    today = today or datetime.now(EASTERN).date()
    events, coverage = price_changes(db, today)
    ledger_path = archive / 'state/price-alerts.json.gz'
    ledger = read_json(ledger_path) if ledger_path.exists() else {'version': 1, 'sent': {}}
    pending = ledger.setdefault('pending', {})
    recipient_key = hashlib.sha256(recipient.strip().lower().encode()).hexdigest()
    queued = dict(pending.get(recipient_key, {}))
    for event in events:
        key = event_key(event, recipient)
        if key not in ledger['sent']:
            queued[key] = event
    queued = {key: event for key, event in queued.items() if key not in ledger['sent']}
    events = sorted(queued.values(), key=lambda event: (event['date'], event['change'] >= 0, -abs(event['percent'])))
    result = dict(status='no_new_changes', changes=len(events), date=today.isoformat(), coverage=coverage)
    if dry_run:
        return dict(result, status='preview', events=events)
    if queued != pending.get(recipient_key, {}):
        pending[recipient_key] = queued
        write_json(ledger_path, ledger)  # Persist before attempting delivery, including missing credentials.
    password = os.environ.get('HOUSING_SMTP_PASSWORD', '')
    if not password:
        return dict(result, status='not_configured', missing='HOUSING_SMTP_PASSWORD')
    if not events:
        return result
    username = os.environ.get('HOUSING_SMTP_USERNAME') or recipient
    message = message_for(events, recipient, username)
    # Failed sends remain eligible on the next batch. Stable IDs also survive enrichment.
    sender(message, username, password)
    stamp = datetime.now(EASTERN).isoformat()
    for event in events:
        ledger['sent'][event_key(event, recipient)] = {'sent_at': stamp, 'date': event['date']}
    pending.pop(recipient_key, None)
    write_json(ledger_path, ledger)
    return dict(result, status='sent')
