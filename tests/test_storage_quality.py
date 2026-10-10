from datetime import datetime, timedelta
import pytest
from sqlalchemy import select
from opportunityscout.database.models import Opportunity, StatusChange, utcnow
from opportunityscout.database.repository import add_note, create_database, expire_events, transition, upsert
from opportunityscout.services.deduplication import matches, normalize_url
from opportunityscout.services.importing import import_csv
from opportunityscout.services.validation import parse_date, validate_record


def test_persistence_and_lifecycle(sessions, paid_record, settings):
    with sessions.begin() as session:
        opportunity, _ = upsert(session, paid_record, 'fixture', '1', settings)
        identifier = opportunity.id
        transition(opportunity, 'Saved')
        transition(opportunity, 'Applied')
        add_note(opportunity, 'Review sent manually')
    with sessions() as session:
        restored = session.get(Opportunity, identifier)
        assert restored.status == 'Applied'
        assert [h.new_status for h in restored.history] == ['New', 'Saved', 'Applied']
        assert restored.notes[0].text == 'Review sent manually'
        assert restored.sources[0].provider == 'fixture'
        assert restored.first_seen <= restored.last_seen


def test_status_validation(paid_record):
    opportunity = Opportunity(**validate_record(paid_record), status='New')
    with pytest.raises(ValueError):
        transition(opportunity, 'Sent Automatically')
    with pytest.raises(ValueError):
        add_note(opportunity, '  ')


def test_source_dedup_preserves_manual_changes(sessions, paid_record, settings):
    with sessions.begin() as session:
        original, _ = upsert(session, paid_record, 'fixture', '1', settings)
        original.title = 'Manually edited title'
        transition(original, 'Applied')
    with sessions.begin() as session:
        refreshed, duplicate = upsert(session, paid_record, 'fixture', '1', settings, raw={'salary': 'Changed'})
        assert duplicate
        assert refreshed.title == 'Manually edited title'
        assert refreshed.status == 'Applied'
        assert refreshed.sources[0].raw == {'salary': 'Changed'}


def test_url_dedup_merges_multiple_sources(sessions, paid_record, settings):
    with sessions.begin() as session:
        original, _ = upsert(session, paid_record, 'fixture', '1', settings)
        record = {**paid_record, 'url': paid_record['url'] + '?utm_source=fixture'}
        matched, duplicate = upsert(session, record, 'another', '2', settings)
        assert duplicate and matched.id == original.id
        assert len(matched.sources) == 2


def test_generic_url_does_not_merge_different_titles(paid_record):
    opportunity = Opportunity(**validate_record(paid_record))
    assert not matches(opportunity, {**paid_record, 'title': 'A completely different job'})


def test_different_event_dates_do_not_merge(settings, sessions):
    record = dict(kind='network', title='Repeated event fixture', organization='Fixture', location='Lehi', url='https://example.org/calendar', event_start='2027-01-02T12:00:00-07:00')
    with sessions.begin() as session:
        first, _ = upsert(session, record, 'fixture', '1', settings)
        second, duplicate = upsert(session, {**record, 'event_start': '2027-01-03T12:00:00-07:00'}, 'fixture', '2', settings)
        assert not duplicate and first.id != second.id


def test_ambiguous_matches_stay_separate(sessions, settings):
    record = dict(kind='income', title='Common title', organization='Common company', location='Lehi')
    with sessions.begin() as session:
        session.add_all([Opportunity(**validate_record(record)), Opportunity(**validate_record(record))])
    with sessions.begin() as session:
        _, duplicate = upsert(session, record, 'fixture', '1', settings)
        assert not duplicate
        assert len(session.scalars(select(Opportunity)).all()) == 3


def test_event_expiration_and_history(sessions, settings):
    with sessions.begin() as session:
        record = dict(kind='network', title='Past fixture', event_start=utcnow()-timedelta(days=1))
        opportunity, _ = upsert(session, record, 'fixture', '1', settings)
        transition(opportunity, 'Attending')
        assert expire_events(session) == 1
        assert opportunity.status == 'Expired'
        assert opportunity.history[-1].old_status == 'Attending'
        assert expire_events(session) == 0


def test_ongoing_event_end_is_respected(sessions, settings):
    with sessions.begin() as session:
        opportunity, _ = upsert(session, dict(kind='network', title='Ongoing fixture', event_start=utcnow()-timedelta(hours=1), event_end=utcnow()+timedelta(hours=1)), 'fixture', '1', settings)
        assert expire_events(session) == 0
        assert opportunity.status == 'New'


def test_datetime_is_not_shifted_twice(settings, sessions):
    expected = datetime(2027, 1, 1, 19)
    assert parse_date('2027-01-01T12:00:00-07:00') == expected
    assert parse_date(expected) == expected
    assert parse_date('2027-01-01T12:00:00') == expected
    with sessions.begin() as session:
        opportunity, _ = upsert(session, dict(kind='network', title='Time fixture', event_start=expected), 'fixture', 'time', settings)
        assert opportunity.event_start == expected


def test_csv_import_is_atomic_and_repeatable(sessions, settings):
    invalid = b'title,amount\nValid fixture,20\nInvalid fixture,-20\n'
    with pytest.raises(ValueError, match='row 3'):
        import_csv(sessions, invalid, settings)
    with sessions() as session:
        assert session.scalars(select(Opportunity)).all() == []
    content = b'title,organization,location,amount\nValid fixture,Company,Lehi,20\n'
    assert import_csv(sessions, content, settings) == (1, 0)
    assert import_csv(sessions, content, settings) == (0, 1)


@pytest.mark.parametrize('value', ['NaN', 'inf', '-1'])
def test_bad_numbers_rejected(value):
    with pytest.raises(ValueError):
        validate_record(dict(title='Fixture', amount=value))


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'file:///etc/passwd', 'https://user:password@example.org'])
def test_unsafe_links_rejected(url):
    with pytest.raises(ValueError):
        validate_record(dict(title='Fixture', url=url))


def test_url_normalization():
    assert normalize_url('https://EXAMPLE.org/job/?utm_source=a&id=1#section') == 'https://example.org/job?id=1'
    assert normalize_url('https://example.org/job?id=2') != normalize_url('https://example.org/job?id=1')
