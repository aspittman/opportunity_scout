"""Manual relationship tracking; never sends messages."""
from ..database.models import Contact, utcnow
from .validation import parse_date

CONTACT_STATUSES = ('New', 'Connected', 'Follow-up Needed', 'Completed', 'Closed')


def update_contact(contact, data, opportunity_lookup):
    name = data.get('name', '').strip()
    if not name:
        raise ValueError('Contact name is required.')
    for key in ('name', 'organization', 'role', 'information', 'met_at', 'notes', 'status'):
        setattr(contact, key, data.get(key, '').strip())
    if contact.status not in CONTACT_STATUSES:
        raise ValueError('Invalid relationship status.')
    contact.followup_at = parse_date(data.get('followup_at'))
    linked = data.get('opportunity_id')
    contact.opportunity_id = opportunity_lookup(int(linked)).id if linked else None
    contact.updated_at = utcnow()
    return contact
