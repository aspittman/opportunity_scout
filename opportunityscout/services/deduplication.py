import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def safe_url(value):
    if not value:
        return ''
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('External links must be public HTTP(S) URLs without credentials.')
    return value.strip()


def normalize_url(url):
    if not url:
        return ''
    parsed = urlsplit(safe_url(url))
    query = sorted((key, value) for key, value in parse_qsl(parsed.query) if not key.lower().startswith('utm_') and key.lower() not in ('fbclid', 'gclid'))
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip('/') or '/', urlencode(query), ''))


def normalized(value):
    return re.sub(r'\W+', ' ', (value or '').casefold()).strip()


def matches(existing, incoming):
    if existing.kind != incoming['kind']:
        return False
    if existing.kind == 'network' and existing.event_start != incoming.get('event_start'):
        return False
    # An identical URL needs an identical title: generic calendar/company URLs are not unique.
    if existing.url and incoming.get('url') and normalize_url(existing.url) == normalize_url(incoming['url']):
        return normalized(existing.title) == normalized(incoming['title'])
    keys = ('title', 'organization', 'location')
    return all(incoming.get(key) and normalized(getattr(existing, key)) == normalized(incoming[key]) for key in keys)
