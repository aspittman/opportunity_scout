from pathlib import Path
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from .models import Base, Opportunity, Source, StatusChange, Note, utcnow
from ..services.deduplication import matches
from ..services.scoring import score
from ..services.validation import STATUSES, validate_record


def create_database(path):
    if path != ':memory:':
        path = str(Path(path).resolve())
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    kwargs = {'poolclass': StaticPool} if path == ':memory:' else {}
    engine = create_engine(f'sqlite:///{path}', connect_args={'check_same_thread': False, 'timeout': 30}, **kwargs)
    @event.listens_for(engine, 'connect')
    def configure_sqlite(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA journal_mode=WAL')
    Base.metadata.create_all(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)


def upsert(session, data, provider, source_id, settings, raw=None):
    record = validate_record(data)
    now = utcnow()
    source = session.scalar(select(Source).where(Source.provider == provider, Source.source_id == str(source_id)))
    opportunity = session.get(Opportunity, source.opportunity_id) if source else None
    if not opportunity:
        candidates = session.scalars(select(Opportunity).where(Opportunity.kind == record['kind'])).all()
        matches_found = [candidate for candidate in candidates if matches(candidate, record)]
        # Ambiguity is preserved as a separate opportunity.
        if len(matches_found) == 1:
            opportunity = matches_found[0]
    duplicate = opportunity is not None
    if opportunity is None:
        opportunity = Opportunity(**record, first_seen=now, last_seen=now, last_verified=now)
        session.add(opportunity)
        session.flush()
        opportunity.history.append(StatusChange(old_status='', new_status='New'))
    # Provider refreshes never overwrite manually edited facts or human workflow state.
    opportunity.last_seen = now
    opportunity.last_verified = now
    if source is None:
        opportunity.sources.append(Source(provider=provider, source_id=str(source_id), url=record['url'], raw=raw or {}))
    else:
        source.url, source.raw, source.last_seen = record['url'], raw or {}, now
    opportunity.score, opportunity.score_details = score(opportunity, settings)
    session.flush()
    return opportunity, duplicate


def transition(opportunity, status):
    if status not in STATUSES:
        raise ValueError('Invalid opportunity status.')
    if status != opportunity.status:
        opportunity.history.append(StatusChange(old_status=opportunity.status, new_status=status))
        opportunity.status = status
        opportunity.updated_at = utcnow()


def add_note(opportunity, text):
    text = text.strip()
    if not text:
        raise ValueError('Note cannot be empty.')
    opportunity.notes.append(Note(text=text))
    opportunity.updated_at = utcnow()


def expire_events(session, now=None):
    now = now or utcnow()
    changed = 0
    for opportunity in session.scalars(select(Opportunity)):
        deadline = opportunity.expires_at
        if opportunity.kind == 'network':
            # A date-only iCal event gets next-day midnight as its end.
            deadline = opportunity.event_end or opportunity.event_start
        if deadline and deadline <= now and opportunity.status not in ('Completed', 'Rejected', 'Expired'):
            transition(opportunity, 'Expired')
            changed += 1
    return changed


def list_opportunities(session, kind, filters=None):
    """Search, filter, and order normalized records without presentation code."""
    from sqlalchemy import or_
    from ..services.validation import number
    filters = filters or {}
    query = select(Opportunity).where(Opportunity.kind == kind)
    search = filters.get('q', '').strip()
    if search:
        escaped = search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        query = query.where(or_(*(getattr(Opportunity, column).ilike(f'%{escaped}%', escape='\\') for column in ('title', 'organization', 'location', 'category'))))
    status = filters.get('status')
    if status:
        query = query.where(Opportunity.status == status)
    elif kind == 'network' and filters.get('show') != 'all':
        query = query.where(Opportunity.status.not_in(('Expired', 'Rejected', 'Completed')))
    if filters.get('remote') in ('true', 'false'):
        query = query.where(Opportunity.remote == (filters['remote'] == 'true'))
    if filters.get('category'):
        query = query.where(Opportunity.category == filters['category'])
    if filters.get('source'):
        query = query.where(Opportunity.sources.any(Source.provider == filters['source']))
    if filters.get('min_score'):
        query = query.where(Opportunity.score >= number(filters['min_score'], 'Minimum score'))
    order = Opportunity.event_start.asc().nulls_last() if kind == 'network' else Opportunity.score.desc()
    return session.scalars(query.order_by(order, Opportunity.first_seen.desc())).all()


def list_records(session, model, sort=None):
    query = select(model)
    if sort:
        query = query.order_by(*sort)
    return session.scalars(query).all()


def categories_for(session, kind):
    return session.scalars(select(Opportunity.category).where(Opportunity.kind == kind).distinct()).all()
