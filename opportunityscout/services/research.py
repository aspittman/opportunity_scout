"""Durable execution history, nonoverlapping processes, and isolated provider errors."""
import fcntl
import threading
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from sqlalchemy import select
from ..database.models import ResearchRun, Opportunity, utcnow
from ..database.repository import upsert, expire_events
from .scoring import score
from ..providers.remotive import RemotiveProvider
from ..providers.utah_calendar import UtahCalendarProvider


def default_providers():
    return [RemotiveProvider(), UtahCalendarProvider()]


class ResearchService:
    def __init__(self, sessions, settings_loader, lock_path, providers=None):
        self.sessions = sessions
        self.settings_loader = settings_loader
        self.providers = providers if providers is not None else default_providers()
        self.lock_path = Path(lock_path)
        self.thread_lock = threading.Lock()

    @contextmanager
    def lock(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open('a') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def run(self, kind=None, due_only=False):
        if not self.thread_lock.acquire(blocking=False):
            return False
        try:
            with self.lock() as acquired:
                if not acquired:
                    return False
                settings = self.settings_loader()
                # Any previous Running row is orphaned once exclusive lock is available.
                with self.sessions.begin() as session:
                    for run in session.scalars(select(ResearchRun).where(ResearchRun.status == 'Running')):
                        run.status, run.completed_at, run.errors = 'Interrupted', utcnow(), 'Previous process stopped before completion.'
                for provider in self.providers:
                    if provider.name not in settings['enabled_providers'] or not settings[f'{provider.kind}_enabled'] or kind and kind != provider.kind:
                        continue
                    with self.sessions.begin() as session:
                        latest = session.scalar(select(ResearchRun).where(ResearchRun.provider == provider.name).order_by(ResearchRun.started_at.desc()))
                        # Persistent rate limiting also covers manual/CLI execution and failures.
                        interval = max(provider.min_interval_hours, settings[f'{provider.kind}_interval_hours']) if due_only else provider.min_interval_hours
                        if latest and utcnow() - latest.started_at < timedelta(hours=interval):
                            continue
                        run = ResearchRun(provider=provider.name)
                        session.add(run)
                        session.flush()
                        run_id = run.id
                    counts = dict(discovered=0, accepted=0, duplicates=0, filtered=0)
                    errors = []
                    status = 'Success'
                    try:
                        records = provider.fetch()
                        counts['discovered'] = len(records)
                        for raw in records:
                            try:
                                record = provider.normalize(raw)
                                if not provider.accepts(record, settings):
                                    counts['filtered'] += 1
                                    continue
                                with self.sessions.begin() as session:
                                    _, duplicate = upsert(session, record, provider.name, record['source_id'], settings, raw=raw)
                                    counts['duplicates' if duplicate else 'accepted'] += 1
                            except Exception as exc:
                                errors.append(f'{type(exc).__name__}: {str(exc)[:300]}')
                        if errors:
                            status = 'Partial' if counts['accepted'] + counts['duplicates'] else 'Failed'
                    except Exception as exc:
                        status = 'Failed'
                        errors.append(f'{type(exc).__name__}: {str(exc)[:500]}')
                    finally:
                        with self.sessions.begin() as session:
                            run = session.get(ResearchRun, run_id)
                            for key, value in counts.items():
                                setattr(run, key, value)
                            run.status, run.completed_at = status, utcnow()
                            run.errors = '\n'.join(errors[:50])
                self.maintenance()
                return True
        finally:
            self.thread_lock.release()

    def maintenance(self):
        settings = self.settings_loader()
        with self.sessions.begin() as session:
            expire_events(session)
            for opportunity in session.scalars(select(Opportunity)):
                opportunity.score, opportunity.score_details = score(opportunity, settings)


def provider_health(runs, providers, settings, now=None):
    now = now or utcnow()
    result = []
    for provider in providers:
        history = sorted((run for run in runs if run.provider == provider.name), key=lambda run: run.started_at, reverse=True)
        latest = history[0] if history else None
        successful = next((run for run in history if run.status == 'Success'), None)
        enabled = provider.name in settings['enabled_providers'] and settings[f'{provider.kind}_enabled']
        if not enabled:
            state = 'Disabled'
        elif not latest:
            state = 'Not run'
        elif latest.status == 'Running':
            state = 'Running' if now - latest.started_at < timedelta(minutes=30) else 'Stalled'
        elif latest.status != 'Success':
            state = latest.status
        elif not latest.completed_at or now - latest.completed_at > timedelta(hours=settings[f'{provider.kind}_interval_hours'] * 1.5):
            state = 'Stale'
        else:
            state = 'Healthy'
        result.append(dict(name=provider.name, state=state, latest=latest, last_success=successful.completed_at if successful else None))
    return result
