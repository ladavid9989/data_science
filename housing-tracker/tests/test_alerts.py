from datetime import date

import pytest

from tracker.alerts import notify, price_changes
from tracker.storage import BAND_SCOPE, import_snapshot

TODAY = date(2026, 10, 4)


def put(db, day, prices, *, quality='source_complete', hour=13, price_day=None, episode='unknown', boundary='zone'):
    rows = [dict(property_id=f'zillow:{i}', episode_id=f'zillow:{i}:{episode}',
                 address=f'{i} Test St', price=price, bedrooms=3, bathrooms=2,
                 property_type='SINGLE_FAMILY', status='active', year_built=None,
                 price_observed_at=f'2026-10-{price_day or day:02d}T13:00:00+00:00',
                 url=f'https://www.zillow.com/homedetails/{i}_zpid/')
            for i, price in enumerate(prices, 1)]
    return import_snapshot(db, dict(schema_version=1, dataset='observed', school='north_gwinnett',
        observed_at=f'2026-10-{day:02d}T{hour:02d}:00:00+00:00', quality=quality,
        scope=BAND_SCOPE + ':' + boundary, boundary_version=boundary, reported_count=len(rows),
        expected_unique_count=len(rows), coverage=dict(price_range=[400000, 700000],
            all_pages=quality == 'source_complete', all_prices=False, query_validated=quality == 'source_complete'),
        source='test fixture', listings=rows))


def test_observed_property_prices_support_unknown_episodes_and_both_directions(tmp_path):
    db = tmp_path / 'db'
    put(db, 3, [600000, 500000, 550000])
    put(db, 4, [570000, 510000, 550000])
    events, _ = price_changes(db, TODAY)
    assert [e['change'] for e in events] == [-30000, 10000]
    assert events[0]['percent'] == -5


@pytest.mark.parametrize('prior_day,quality,boundary', [(2, 'source_complete', 'zone'),
    (3, 'partial', 'zone'), (3, 'source_complete', 'new-zone')])
def test_missing_incomplete_or_incompatible_previous_day_suppresses_alert(tmp_path, prior_day, quality, boundary):
    db = tmp_path / 'db'
    put(db, prior_day, [600000])
    put(db, 4, [570000], quality=quality, boundary=boundary)
    assert price_changes(db, TODAY)[0] == []


def test_stale_price_and_explicit_relisting_do_not_trigger(tmp_path):
    db = tmp_path / 'db'
    put(db, 3, [600000], episode='first')
    put(db, 4, [570000], episode='second')
    assert price_changes(db, TODAY)[0] == []
    put(db, 4, [560000], hour=14, price_day=3, episode='first')
    assert price_changes(db, TODAY)[0] == []


def test_email_sent_once_despite_repeated_enrichment_and_runs(tmp_path, monkeypatch):
    db, archive = tmp_path / 'db', tmp_path / 'archive'
    monkeypatch.setenv('HOUSING_SMTP_PASSWORD', 'test-only')
    put(db, 3, [600000])
    put(db, 4, [570000])
    sent = []
    send = lambda message, *args: sent.append(message)
    assert notify(db, archive, 'owner@example.com', today=TODAY, sender=send)['status'] == 'sent'
    put(db, 4, [570000], hour=14)  # Year enrichment must not resend the price alert.
    assert notify(db, archive, 'owner@example.com', today=TODAY, sender=send)['status'] == 'no_new_changes'
    assert len(sent) == 1
    assert sent[0]['To'] == 'owner@example.com'
    assert '$600,000' in sent[0].get_content() and '$570,000' in sent[0].get_content()
    assert 'EDT' in sent[0].get_content()


def test_failed_send_retries_and_preview_never_sends(tmp_path, monkeypatch):
    db, archive = tmp_path / 'db', tmp_path / 'archive'
    monkeypatch.setenv('HOUSING_SMTP_PASSWORD', 'test-only')
    put(db, 3, [600000])
    put(db, 4, [570000])
    def fail(*args):
        raise OSError('test SMTP failure')
    assert notify(db, archive, 'owner@example.com', today=TODAY, dry_run=True, sender=fail)['changes'] == 1
    with pytest.raises(OSError):
        notify(db, archive, 'owner@example.com', today=TODAY, sender=fail)
    from tracker.collect import read_json
    ledger = read_json(archive / 'state/price-alerts.json.gz')
    assert ledger['pending'] and not ledger['sent']
    # Retry remains possible after midnight even when no new price snapshot is available.
    assert notify(db, archive, 'owner@example.com', today=date(2026, 10, 5), sender=lambda *a: None)['status'] == 'sent'


def test_missing_credentials_are_visible_without_marking_sent(tmp_path, monkeypatch):
    db = tmp_path / 'db'
    monkeypatch.delenv('HOUSING_SMTP_PASSWORD', raising=False)
    put(db, 3, [600000])
    put(db, 4, [570000])
    result = notify(db, tmp_path / 'archive', 'owner@example.com', today=TODAY)
    assert result['status'] == 'not_configured' and result['changes'] == 1


def test_eastern_day_boundary(tmp_path):
    db = tmp_path / 'db'
    put(db, 3, [600000])
    # 00:00 UTC Oct 4 is still Oct 3 in Georgia: not a new comparison day.
    put(db, 4, [570000], hour=0)
    assert price_changes(db, TODAY)[0] == []


def test_new_recipient_gets_alert_without_resending_to_existing_recipient(tmp_path, monkeypatch):
    db, archive = tmp_path / 'db', tmp_path / 'archive'
    monkeypatch.setenv('HOUSING_SMTP_PASSWORD', 'test-only')
    monkeypatch.setenv('HOUSING_SMTP_USERNAME', 'sender@example.com')
    put(db, 3, [600000])
    put(db, 4, [570000])
    sent = []
    def send(message, username, password):
        assert username == 'sender@example.com'
        sent.append(message['To'])
    for recipient in ('first@example.com', 'first@example.com', 'second@example.com', 'second@example.com'):
        notify(db, archive, recipient, today=TODAY, sender=send)
    assert sent == ['first@example.com', 'second@example.com']


def test_cli_continues_to_second_recipient_when_first_fails(tmp_path, monkeypatch):
    from tracker import alerts, cli
    visited = []
    def deliver(db, archive, recipient, **kwargs):
        visited.append(recipient)
        if recipient == 'first@example.com':
            raise OSError('test failure')
        return dict(status='sent', changes=1)
    monkeypatch.setattr(alerts, 'notify', deliver)
    monkeypatch.setattr('sys.argv', ['tracker', 'email-price-changes', '--archive', str(tmp_path),
                                   '--to', 'first@example.com', 'second@example.com'])
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 1
    assert visited == ['first@example.com', 'second@example.com']


def test_smtp_connection_fallback_and_no_quit_failure(monkeypatch):
    import smtplib
    from tracker.alerts import send_message
    calls = []
    class Connection:
        def login(self, *args, **kwargs):
            assert kwargs['initial_response_ok'] is False
            calls.append('login')
        def send_message(self, message): calls.append('accepted')
        def close(self): calls.append('closed')
        def quit(self): raise smtplib.SMTPServerDisconnected('QUIT after acceptance')
    def disconnected(*args, **kwargs):
        calls.append('587')
        raise smtplib.SMTPServerDisconnected('connect failed')
    monkeypatch.setattr(smtplib, 'SMTP', disconnected)
    monkeypatch.setattr(smtplib, 'SMTP_SSL', lambda *a, **k: Connection())
    send_message(None, 'sender@example.com', 'test-only')
    assert calls == ['587', 'login', 'accepted', 'closed']


def test_smtp_send_disconnect_is_not_immediately_resent(monkeypatch):
    import smtplib
    from tracker.alerts import send_message, DeliveryFailure
    class Connection:
        def ehlo(self): pass
        def starttls(self, **kwargs): pass
        def login(self, *args, **kwargs): pass
        def send_message(self, message): raise smtplib.SMTPServerDisconnected('ambiguous acceptance')
        def close(self): pass
    monkeypatch.setattr(smtplib, 'SMTP', lambda *a, **k: Connection())
    monkeypatch.setattr(smtplib, 'SMTP_SSL', lambda *a, **k: pytest.fail('must not resend immediately'))
    with pytest.raises(DeliveryFailure) as exc:
        send_message(None, 'sender@example.com', 'test-only')
    assert exc.value.attempts[0]['stage'] == 'send'
