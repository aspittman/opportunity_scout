"""Shared manual/import/provider input validation."""
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from .deduplication import safe_url

STATUSES = ('New', 'Reviewing', 'Saved', 'Applied', 'Contacted', 'Interview Scheduled', 'Attending', 'Follow-up Needed', 'Offer Received', 'Active', 'Completed', 'Rejected', 'Expired')
TEXT_FIELDS = ('title', 'organization', 'category', 'location', 'url', 'description', 'target_audience', 'industries', 'employment_value', 'business_value', 'compensation_text', 'arrangement')
NUM_FIELDS = ('admission_cost', 'amount', 'work_hours', 'travel_hours', 'preparation_hours', 'expenses', 'annual_hours', 'weekly_hours', 'distance_miles')
DATE_FIELDS = ('event_start', 'event_end', 'expires_at')


def parse_date(value):
    if not value:
        return None
    internal = isinstance(value, datetime)
    dt = value if internal else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc if internal else ZoneInfo('America/Denver'))
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def number(value, key, required=False):
    if value in (None, ''):
        if required:
            raise ValueError(f'{key} is required.')
        return None
    if isinstance(value, bool):
        raise ValueError(f'{key} must be a number.')
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f'{key} must be finite and nonnegative.')
    return result


def boolean(value):
    if value in (None, '', 'unknown'):
        return None
    if value in (True, 'true', 'True', '1', 'yes'):
        return True
    if value in (False, 'false', 'False', '0', 'no'):
        return False
    raise ValueError('Boolean fields must be true, false, or unknown.')


def validate_record(data):
    if not isinstance(data, dict) and not hasattr(data, 'get'):
        raise ValueError('Opportunity data must be an object.')
    kind = data.get('kind', 'income')
    if kind not in ('income', 'network'):
        raise ValueError('Kind must be income or network.')
    record = {key: str(data.get(key) or '').strip() for key in TEXT_FIELDS}
    if not record['title'] or len(record['title']) > 500:
        raise ValueError('Title is required and must be at most 500 characters.')
    record['kind'] = kind
    record['url'] = safe_url(record['url'])
    record.update({key: number(data.get(key), key) for key in NUM_FIELDS})
    record.update({key: parse_date(data.get(key)) for key in DATE_FIELDS})
    record.update({key: boolean(data.get(key)) for key in ('remote', 'flexible')})
    record['compensation_type'] = data.get('compensation_type') or 'unknown'
    record['pay_basis'] = data.get('pay_basis') or 'unknown'
    if record['compensation_type'] not in ('unknown', 'hourly', 'salary', 'fixed'):
        raise ValueError('Invalid compensation type.')
    if record['pay_basis'] not in ('unknown', 'employee_gross', 'contractor_gross', 'reported_net'):
        raise ValueError('Invalid pay basis.')
    if record['event_end'] and record['event_start'] and record['event_end'] < record['event_start']:
        raise ValueError('Event end precedes start.')
    evidence = data.get('evidence') or {}
    if not isinstance(evidence, dict):
        raise ValueError('Evidence must be an object.')
    for key, assessment in evidence.items():
        if key not in ('earning', 'fit', 'career') or not isinstance(assessment, dict) or not isinstance(assessment.get('reason'), str) or not assessment['reason'].strip():
            raise ValueError('Assessments require an earning/fit/career dimension and written reason.')
        value = number(assessment.get('value'), 'Assessment score', required=True)
        if value > 100:
            raise ValueError('Assessment scores must be at most 100.')
    record['evidence'] = evidence
    return record
