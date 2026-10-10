import io
import json
from datetime import timedelta
import pytest
from sqlalchemy import select
from opportunityscout.database.models import Contact, Earning, Opportunity, utcnow
from opportunityscout.database.repository import upsert
from opportunityscout.config import validate_settings
from conftest import token


@pytest.mark.parametrize('path', ['/', '/income', '/events', '/events?view=calendar', '/contacts', '/earnings', '/research', '/settings', '/import', '/opportunities/new', '/api/opportunities', '/api/health'])
def test_empty_dashboard_renders(client, path):
    assert client.get(path).status_code == 200


def test_manual_entry_edit_status_and_notes(client, app, paid_record):
    csrf = token(client)
    form = {key: str(value).lower() if isinstance(value, bool) else value for key, value in paid_record.items() if key != 'evidence'}
    response = client.post('/opportunities/new', data={**form, 'csrf_token': csrf})
    assert response.status_code == 302
    detail = response.headers['Location']
    assert client.get(detail).status_code == 200
    assert client.get(detail+'/edit').status_code == 200
    response = client.post(detail+'/status', data={'csrf_token': csrf, 'status': 'Saved', 'note': 'Worth reviewing'})
    assert response.status_code == 302
    assert client.post(detail+'/notes', data={'csrf_token': csrf, 'note': 'Contact tomorrow'}).status_code == 302
    response = client.post(detail+'/edit', data={**form, 'csrf_token': csrf, 'title': 'Updated real lead'})
    assert response.status_code == 302
    with app.extensions['sessions']() as session:
        opportunity = session.scalar(select(Opportunity))
        assert opportunity.status == 'Saved'
        assert opportunity.title == 'Updated real lead'
        assert len(opportunity.notes) == 2
        assert len(opportunity.history) == 2


def test_contacts_and_earnings_are_persisted(client, app):
    csrf = token(client)
    assert client.post('/contacts', data=dict(csrf_token=csrf, name='Fixture Contact', status='New', information='private@example.org')).status_code == 302
    assert client.get('/').status_code == 200  # unknown follow-up date must not break totals
    with app.extensions['sessions']() as session:
        contact = session.scalar(select(Contact))
        identifier = contact.id
        assert contact.information == 'private@example.org'
    assert client.get(f'/contacts?edit={identifier}').status_code == 200
    assert client.post('/contacts', data=dict(csrf_token=csrf, id=identifier, name='Fixture Contact', status='Completed', followup_at='2027-02-01T10:00')).status_code == 302
    assert client.post('/earnings', data=dict(csrf_token=csrf, date='2026-10-10', gross=200, expenses=20, hours=5)).status_code == 302
    with app.extensions['sessions']() as session:
        assert session.scalar(select(Earning)).gross == 200
    assert client.get('/earnings').status_code == 200


def test_missing_csrf_and_external_host_rejected(client):
    assert client.post('/opportunities/new', data=dict(title='Unauthorized')).status_code == 403
    assert client.get('/', headers={'Host': 'evil.example'}).status_code == 400
    csrf = token(client)
    assert client.post('/opportunities/new', headers={'Origin': 'https://evil.example'}, data=dict(csrf_token=csrf, title='Cross-origin')).status_code == 403


def test_security_headers_and_html_escaping(client, app, paid_record, settings):
    with app.extensions['sessions'].begin() as session:
        upsert(session, {**paid_record, 'title': '<script>alert(1)</script>', 'description': '<img src=x onerror=alert(1)>'}, 'fixture', '1', settings)
    response = client.get('/income')
    assert b'&lt;script&gt;' in response.data
    assert b'<script>alert(1)</script>' not in response.data
    assert response.headers['Cache-Control'] == 'no-store'
    assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']


def test_api_read_and_update(client, app, paid_record, settings):
    with app.extensions['sessions'].begin() as session:
        opportunity, _ = upsert(session, paid_record, 'fixture', '1', settings)
        identifier = opportunity.id
    csrf = token(client)
    response = client.patch(f'/api/opportunities/{identifier}', json=dict(status='Applied', note='Manual application recorded'), headers={'X-CSRF-Token': csrf})
    assert response.status_code == 200
    assert response.json['status'] == 'Applied'
    assert response.json['first_seen'].endswith('Z')
    assert client.patch(f'/api/opportunities/{identifier}', json=dict(status='Invalid'), headers={'X-CSRF-Token': csrf}).status_code == 400
    assert client.get('/api/health').json['database'] == 'available'


def test_csv_dashboard_import(client):
    csrf = token(client)
    response = client.post('/import', data={'csrf_token': csrf, 'file': (io.BytesIO(b'title,kind\nImported fixture,income\n'), 'test.csv')}, content_type='multipart/form-data')
    assert response.status_code == 302
    assert b'Imported fixture' in client.get('/income').data


def test_calendar_handles_unknown_and_known_dates(client, app, settings):
    with app.extensions['sessions'].begin() as session:
        for index, dt in enumerate((None, utcnow()+timedelta(days=1))):
            upsert(session, dict(kind='network', title=f'Event fixture {index}', event_start=dt), 'fixture', str(index), settings)
    response = client.get('/events?view=calendar')
    assert response.status_code == 200
    assert b'Unknown' in response.data
    assert b'Event fixture 1' in response.data


def test_filters(client, app, paid_record, settings):
    with app.extensions['sessions'].begin() as session:
        upsert(session, paid_record, 'manual', '1', settings)
    assert len(client.get('/api/opportunities?q=Website&remote=true&source=manual&min_score=75').json) == 1
    assert client.get('/api/opportunities?q=NoMatch').json == []
    assert client.get('/api/opportunities?remote=false').json == []
    assert client.get('/api/opportunities?q=%25').json == []


def test_settings_save_validation_and_rescoring(client, app, settings):
    csrf = token(client)
    updated = {**settings, 'baseline_hourly': 21}
    response = client.post('/settings', data=dict(csrf_token=csrf, settings=json.dumps(updated)))
    assert response.status_code == 302
    assert json.loads(open(app.config['SETTINGS_PATH']).read())['baseline_hourly'] == 21
    response = client.post('/settings', data=dict(csrf_token=csrf, settings='{}'))
    assert response.status_code == 400


def test_invalid_settings_rejected(settings):
    with pytest.raises(ValueError):
        validate_settings({**settings, 'income_weights': dict(earning=10)})
    with pytest.raises(ValueError):
        validate_settings({**settings, 'income_interval_hours': 1})
    with pytest.raises(ValueError):
        validate_settings({**settings, 'enabled_providers': ['unknown']})


def test_expired_event_marks_on_dashboard_read(client, app, settings):
    with app.extensions['sessions'].begin() as session:
        opportunity, _ = upsert(session, dict(kind='network', title='Past fixture', event_start=utcnow()-timedelta(days=1)), 'fixture', '1', settings)
        identifier = opportunity.id
    assert b'Past fixture' not in client.get('/events').data
    assert client.get(f'/api/opportunities/{identifier}').json['status'] == 'Expired'
