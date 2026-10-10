"""Atomic UTF-8 CSV import with deterministic identities and row-level errors."""
import csv
import hashlib
import io
import json
from ..database.repository import upsert
from .validation import validate_record


def import_csv(sessions, content, settings):
    if len(content) > 2 * 1024 * 1024:
        raise ValueError('CSV must be smaller than 2 MB.')
    reader = csv.DictReader(io.StringIO(content.decode('utf-8-sig')))
    if not reader.fieldnames or 'title' not in reader.fieldnames:
        raise ValueError('CSV requires a title header.')
    rows = []
    for index, raw in enumerate(reader, 2):
        if len(rows) >= 2000:
            raise ValueError('CSV must contain at most 2,000 records.')
        try:
            if None in raw:
                raise ValueError('Row has more values than headers.')
            normalized = validate_record(raw)
        except (ValueError, TypeError) as exc:
            raise ValueError(f'CSV row {index}: {exc}') from exc
        identity = {key: normalized[key] for key in ('kind', 'title', 'organization', 'location', 'url', 'event_start')}
        source_id = raw.get('source_id') or hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()
        rows.append((normalized, source_id, raw))
    added = duplicates = 0
    with sessions.begin() as session:
        for record, source_id, raw in rows:
            _, duplicate = upsert(session, record, 'csv', source_id, settings, raw)
            duplicates += int(duplicate)
            added += int(not duplicate)
    return added, duplicates
