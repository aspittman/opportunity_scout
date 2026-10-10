from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from icalendar import Calendar
from .base import Provider, PublicClient
from ..services.validation import parse_date


class UtahCalendarProvider(Provider):
    name = 'utah_tech_calendar'
    kind = 'network'
    endpoint = 'https://utahtechcalendar.com/api/ical'

    def __init__(self, client=None):
        self.client = client or PublicClient()

    def fetch(self):
        response = self.client.get(self.endpoint)
        if 'BEGIN:VCALENDAR' not in response.text or 'END:VCALENDAR' not in response.text:
            raise ValueError('Source did not return a complete iCalendar feed.')
        calendar = Calendar.from_ical(response.content)
        records = []
        for event in calendar.walk('VEVENT'):
            raw = {key: str(event.get(key, '')) for key in ('UID', 'SUMMARY', 'LOCATION', 'DESCRIPTION', 'URL', 'ORGANIZER', 'STATUS')}
            for key in ('DTSTART', 'DTEND'):
                if event.get(key):
                    value = event.decoded(key)
                    if isinstance(value, datetime):
                        raw[key] = value.isoformat()
                    elif isinstance(value, date):
                        raw[key] = value.isoformat()
            # Recurrence expansion requires explicit support; never fabricate occurrences.
            raw['recurring'] = bool(event.get('RRULE') or event.get('RECURRENCE-ID'))
            records.append(raw)
        return records

    def normalize(self, raw):
        if raw.get('recurring'):
            raise ValueError('Recurring VEVENT requires recurrence expansion; import explicit occurrences manually.')
        if not raw.get('UID') or not raw.get('SUMMARY') or not raw.get('DTSTART'):
            raise ValueError('Event requires UID, title, and a source-supplied date.')
        if raw.get('STATUS') == 'CANCELLED':
            raise ValueError('Cancelled event skipped.')
        start = parse_date(raw['DTSTART'])
        end = parse_date(raw.get('DTEND'))
        if len(raw['DTSTART']) == 10 and end is None:
            next_day = date.fromisoformat(raw['DTSTART']) + timedelta(days=1)
            end = parse_date(datetime.combine(next_day, time(), ZoneInfo('America/Denver')))
        return dict(kind='network', title=raw['SUMMARY'], organization=raw.get('ORGANIZER', '').removeprefix('mailto:'),
                    location=raw.get('LOCATION', ''), description=raw.get('DESCRIPTION', ''),
                    category='Technology networking', event_start=start, event_end=end,
                    url=raw.get('URL', ''), source_id=raw['UID'],
                    target_audience='Technology community (inferred from calendar scope)',
                    industries='technology (calendar scope; verify event details)',
                    business_value='Potential professional connections (inferred); no attendance or leads verified.',
                    employment_value='Potential career connections (inferred); hiring activity unverified.')

    def accepts(self, record, settings):
        text = record['location'].lower()
        # Unknown venue is retained for review; known venues must match configured local targets.
        return not text or any(place.lower() in text for place in settings['locations'])
