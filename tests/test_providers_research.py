from datetime import timedelta
from unittest.mock import Mock
import pytest
import requests
from sqlalchemy import select
from opportunityscout.database.models import Opportunity, ResearchRun, utcnow
from opportunityscout.providers.base import PublicClient
from opportunityscout.providers.remotive import RemotiveProvider
from opportunityscout.providers.utah_calendar import UtahCalendarProvider
from opportunityscout.services.research import ResearchService, provider_health

JOB = dict(id=42, title='Python automation fixture', url='https://remotive.com/remote-jobs/fixture/42', company_name='Fixture Company', category='Software Development', salary='$40,000 - $50,000', candidate_required_location='USA', description='<p>Build <strong>automation</strong></p>', job_type='contract')
ICS = b'''BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//OpportunityScout tests//EN\r
BEGIN:VEVENT\r
UID:fixture-1\r
DTSTART;TZID=America/Denver:20270115T180000\r
DTEND;TZID=America/Denver:20270115T200000\r
SUMMARY:Fixture developer meetup\r
LOCATION:Lehi\r
URL:https://example.org/fixture-event\r
DESCRIPTION:First line\\nSecond line\r
END:VEVENT\r
END:VCALENDAR\r
'''


def mock_response(content=None, payload=None):
    response = Mock()
    response.json.return_value = payload
    response.content = content or b''
    response.text = response.content.decode()
    return response


def test_remotive_retrieval_and_normalization(settings):
    client = Mock()
    client.get.return_value = mock_response(payload={'jobs': [JOB]})
    provider = RemotiveProvider(client)
    record = provider.normalize(provider.fetch()[0])
    assert record['title'] == JOB['title']
    assert record['compensation_text'] == '$40,000 - $50,000'
    assert record['compensation_type'] == 'unknown'
    assert 'amount' not in record
    assert record['description'] == 'Build automation'
    assert provider.accepts(record, settings)
    assert not provider.accepts({**record, 'location': 'Europe'}, settings)
    assert not provider.accepts({**record, 'location': ''}, settings)
    assert provider.accepts({**record, 'location': 'Worldwide'}, settings)
    client.get.assert_called_once_with(provider.endpoint, check_robots=False)


def test_remotive_malformed_payload_fails():
    client = Mock()
    client.get.return_value = mock_response(payload={'message': 'Unavailable'})
    with pytest.raises(ValueError, match='invalid jobs'):
        RemotiveProvider(client).fetch()


def test_event_feed_normalization(settings):
    client = Mock()
    client.get.return_value = mock_response(content=ICS)
    provider = UtahCalendarProvider(client)
    raw = provider.fetch()[0]
    record = provider.normalize(raw)
    assert record['event_start'].hour == 1
    assert record['event_start'].day == 16
    assert record['event_end'].hour == 3
    assert record['organization'] == ''
    assert 'admission_cost' not in record
    assert record['description'] == 'First line\nSecond line'
    assert provider.accepts(record, settings)
    assert not provider.accepts({**record, 'location': 'St. George'}, settings)
    assert provider.accepts({**record, 'location': ''}, settings)


def test_all_day_event_and_recurrences():
    provider = UtahCalendarProvider(Mock())
    record = provider.normalize(dict(UID='fixture', SUMMARY='All-day fixture', DTSTART='2027-01-10'))
    assert record['event_end']-record['event_start'] == timedelta(days=1)
    with pytest.raises(ValueError, match='Recurring'):
        provider.normalize(dict(UID='fixture', SUMMARY='Recurring fixture', DTSTART='2027-01-10', recurring=True))
    with pytest.raises(ValueError, match='source-supplied date'):
        provider.normalize(dict(UID='fixture', SUMMARY='No date'))


def test_invalid_ical_response_fails():
    client = Mock()
    client.get.return_value = mock_response(content=b'<html>Blocked</html>')
    with pytest.raises(ValueError, match='complete iCalendar'):
        UtahCalendarProvider(client).fetch()


def service(sessions, tmp_path, settings, providers):
    return ResearchService(sessions, lambda: settings, tmp_path/'research.lock', providers)


def test_failure_is_recorded_and_other_provider_still_runs(sessions, tmp_path, settings):
    job_client, event_client = Mock(), Mock()
    job_client.get.side_effect = requests.Timeout('Fixture timeout')
    event_client.get.return_value = mock_response(content=ICS)
    research = service(sessions, tmp_path, settings, [RemotiveProvider(job_client), UtahCalendarProvider(event_client)])
    assert research.run()
    with sessions() as session:
        runs = session.scalars(select(ResearchRun).order_by(ResearchRun.id)).all()
        assert [run.status for run in runs] == ['Failed', 'Success']
        assert 'Fixture timeout' in runs[0].errors
        assert runs[0].completed_at is not None
        assert runs[1].accepted == 1 and runs[1].discovered == 1
        assert len(session.scalars(select(Opportunity)).all()) == 1


def test_partial_run_counters(sessions, tmp_path, settings):
    client = Mock()
    client.get.return_value = mock_response(payload={'jobs': [JOB, JOB, {**JOB, 'id': 43, 'candidate_required_location': 'Europe'}, {'invalid': True}]})
    research = service(sessions, tmp_path, settings, [RemotiveProvider(client)])
    research.run()
    with sessions() as session:
        run = session.scalar(select(ResearchRun))
        assert run.status == 'Partial'
        assert (run.discovered, run.accepted, run.duplicates, run.filtered) == (4, 1, 1, 1)
        assert run.errors


def test_provider_cooldown_prevents_repeated_fetch(sessions, tmp_path, settings):
    client = Mock()
    client.get.return_value = mock_response(payload={'jobs': [JOB]})
    research = service(sessions, tmp_path, settings, [RemotiveProvider(client)])
    research.run()
    research.run()
    assert client.get.call_count == 1


def test_due_intervals_are_independent(sessions, tmp_path, settings):
    settings['income_interval_hours'] = 12
    settings['network_interval_hours'] = 48
    with sessions.begin() as session:
        session.add_all([ResearchRun(provider=name, started_at=utcnow()-timedelta(hours=25), completed_at=utcnow()-timedelta(hours=25), status='Success') for name in ('remotive', 'utah_tech_calendar')])
    jobs, events = Mock(), Mock()
    jobs.get.return_value = mock_response(payload={'jobs': []})
    research = service(sessions, tmp_path, settings, [RemotiveProvider(jobs), UtahCalendarProvider(events)])
    research.run(due_only=True)
    assert jobs.get.call_count == 1
    assert events.get.call_count == 0


def test_research_lock_prevents_overlap(sessions, tmp_path, settings):
    first = service(sessions, tmp_path, settings, [])
    second = service(sessions, tmp_path, settings, [])
    with first.lock() as acquired:
        assert acquired
        assert second.run() is False


def test_orphaned_run_becomes_interrupted(sessions, tmp_path, settings):
    with sessions.begin() as session:
        session.add(ResearchRun(provider='remotive', status='Running'))
    research = service(sessions, tmp_path, settings, [])
    research.run()
    with sessions() as session:
        run = session.scalar(select(ResearchRun))
        assert run.status == 'Interrupted'
        assert run.completed_at


def test_health_uses_latest_run_and_freshness(settings):
    now = utcnow()
    success = ResearchRun(provider='remotive', started_at=now-timedelta(hours=2), completed_at=now-timedelta(hours=1), status='Success')
    failure = ResearchRun(provider='remotive', started_at=now, completed_at=now, status='Failed')
    provider = RemotiveProvider(Mock())
    assert provider_health([success], [provider], settings, now)[0]['state'] == 'Healthy'
    assert provider_health([success, failure], [provider], settings, now)[0]['state'] == 'Failed'
    assert provider_health([success], [provider], settings, now+timedelta(days=3))[0]['state'] == 'Stale'
    assert provider_health([], [provider], settings, now)[0]['state'] == 'Not run'
    stalled = ResearchRun(provider='remotive', started_at=now-timedelta(hours=1), status='Running')
    assert provider_health([stalled], [provider], settings, now)[0]['state'] == 'Stalled'
    settings['income_enabled'] = False
    assert provider_health([success], [provider], settings, now)[0]['state'] == 'Disabled'


def test_robots_denial_stops_feed_retrieval(monkeypatch):
    client = PublicClient()
    response = mock_response(content=b'User-agent: *\nDisallow: /api/\n')
    fetch = Mock(return_value=response)
    monkeypatch.setattr(client, '_get', fetch)
    with pytest.raises(ValueError, match='disallows'):
        client.get('https://example.org/api/ical')
    assert fetch.call_count == 1


def test_missing_robots_allows_published_feed(monkeypatch):
    client = PublicClient()
    response = Mock(status_code=404)
    missing = requests.HTTPError(response=response)
    fetch = Mock(side_effect=[missing, mock_response(content=ICS)])
    monkeypatch.setattr(client, '_get', fetch)
    assert 'BEGIN:VCALENDAR' in client.get('https://example.org/api/ical').text
    assert fetch.call_count == 2
