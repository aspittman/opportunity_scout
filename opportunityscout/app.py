"""Local Flask dashboard and API; providers never block request handling."""
import hmac
import json
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo
from flask import Flask, abort, flash, g, jsonify, redirect, render_template, request, session, url_for
from .config import ROOT, load_settings, validate_settings
from .database.models import Contact, Earning, Opportunity, ResearchRun, utcnow
from .database.repository import add_note, categories_for, create_database, expire_events, list_opportunities, list_records, transition, upsert
from .services.earnings import estimate, income_summary
from .services.contacts import update_contact
from .services.importing import import_csv
from .services.research import ResearchService, provider_health
from .services.scoring import score
from .services.validation import DATE_FIELDS, NUM_FIELDS, STATUSES, TEXT_FIELDS, number, parse_date, validate_record


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(SECRET_KEY=os.getenv('OPPORTUNITYSCOUT_SECRET_KEY') or secrets.token_hex(32),
                      DATABASE=os.getenv('OPPORTUNITYSCOUT_DATABASE', str(ROOT / 'data/opportunityscout.db')),
                      SETTINGS_PATH=os.getenv('OPPORTUNITYSCOUT_SETTINGS', str(ROOT / 'settings.json')),
                      MAX_CONTENT_LENGTH=2 * 1024 * 1024,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict')
    if test_config:
        app.config.update(test_config)
    for key in ('DATABASE', 'SETTINGS_PATH'):
        if app.config[key] != ':memory:':
            app.config[key] = str((ROOT / app.config[key]).resolve())
    settings_loader = lambda: load_settings(app.config['SETTINGS_PATH'])
    settings_loader()
    engine, sessions = create_database(app.config['DATABASE'])
    app.extensions.update(engine=engine, sessions=sessions)
    research = ResearchService(sessions, settings_loader, str(app.config['DATABASE']) + '.research.lock')
    app.extensions['research'] = research
    app.extensions['dispatch_lock'] = threading.Lock()

    @app.before_request
    def secure_and_open_session():
        # Reject DNS rebinding and cross-site mutation even though the service binds locally.
        if request.host.split(':')[0] not in ('127.0.0.1', 'localhost', '[::1]'):
            abort(400, 'This application only accepts localhost requests.')
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            origin = request.headers.get('Origin')
            if origin and origin != request.host_url.rstrip('/'):
                abort(403, 'Cross-origin requests are disabled.')
            supplied = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
            if not hmac.compare_digest(str(supplied).encode(), str(session.get('csrf_token', '')).encode()) or not supplied:
                abort(403, 'Missing or invalid CSRF token; reload the page.')
        session.setdefault('csrf_token', secrets.token_hex(32))
        g.db = sessions()
        g.settings = settings_loader()
        # Expire on reads too, so an offline/unscheduled dashboard stays accurate.
        expire_events(g.db)
        g.db.commit()

    @app.teardown_request
    def close_session(_error):
        if hasattr(g, 'db'):
            g.db.close()

    @app.after_request
    def security_headers(response):
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.context_processor
    def shared_context():
        return dict(settings=getattr(g, 'settings', {}), statuses=STATUSES, csrf_token=session.get('csrf_token'), estimate=estimate,
                    current_path=request.path, now=utcnow())

    @app.template_filter('localtime')
    def localtime(value, fmt='%b %d, %Y · %I:%M %p'):
        if not value:
            return 'Unknown'
        return value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('America/Denver')).strftime(fmt)

    @app.template_filter('inputdate')
    def inputdate(value):
        return localtime(value, '%Y-%m-%dT%H:%M') if value else ''

    @app.errorhandler(ValueError)
    def invalid_input(error):
        if hasattr(g, 'db'):
            g.db.rollback()
        if request.path.startswith('/api/'):
            return jsonify(error=str(error)), 400
        return render_template('error.html', title='Check your input', message=str(error)), 400

    @app.errorhandler(404)
    @app.errorhandler(403)
    @app.errorhandler(400)
    @app.errorhandler(413)
    def http_error(error):
        if request.path.startswith('/api/'):
            return jsonify(error=str(error.description)), error.code
        return render_template('error.html', title=f'Error {error.code}', message=error.description), error.code

    def get_opportunity(identifier):
        opportunity = g.db.get(Opportunity, identifier)
        if not opportunity:
            abort(404)
        return opportunity

    def all_runs():
        return list_records(g.db, ResearchRun, [ResearchRun.started_at.desc()])

    def filtered_opportunities(kind):
        return list_opportunities(g.db, kind, request.args)

    @app.get('/')
    def overview():
        opportunities = list_records(g.db, Opportunity)
        earnings = list_records(g.db, Earning)
        contacts = list_records(g.db, Contact)
        runs = all_runs()
        open_statuses = set(STATUSES) - {'Completed', 'Rejected', 'Expired'}
        recommendations = sorted((o for o in opportunities if o.status in open_statuses), key=lambda o: o.score, reverse=True)[:6]
        successful = next((r.completed_at for r in runs if r.status == 'Success'), None)
        stats = dict(total=len(opportunities), high=sum(o.score >= 75 and o.status in open_statuses for o in opportunities),
                     new=sum(o.status == 'New' for o in opportunities),
                     upcoming=sum(o.kind == 'network' and o.event_start and o.event_start > utcnow() and o.status in open_statuses for o in opportunities),
                     followups=sum(o.status == 'Follow-up Needed' for o in opportunities) + sum(bool(c.followup_at and c.followup_at <= utcnow() and c.status not in ('Closed', 'Completed')) for c in contacts),
                     active=sum(o.kind == 'income' and o.status == 'Active' for o in opportunities))
        return render_template('overview.html', title='Overview', stats=stats, recommendations=recommendations,
                               health=provider_health(runs, research.providers, g.settings), last_success=successful,
                               income=income_summary(opportunities, earnings, g.settings))

    @app.get('/income')
    @app.get('/events')
    def opportunities():
        kind = 'network' if request.path == '/events' else 'income'
        records = filtered_opportunities(kind)
        categories = categories_for(g.db, kind)
        calendar_groups = {}
        for opportunity in records:
            day = localtime(opportunity.event_start, '%A, %B %d, %Y')
            calendar_groups.setdefault(day, []).append(opportunity)
        return render_template('opportunities.html', title='Networking events' if kind == 'network' else 'Income opportunities', kind=kind, records=records, categories=categories,
                               view=request.args.get('view', 'list'), calendar_groups=calendar_groups)

    @app.route('/opportunities/new', methods=['GET', 'POST'])
    def new_opportunity():
        if request.method == 'POST':
            opportunity, duplicate = upsert(g.db, request.form, 'manual', str(uuid4()), g.settings, raw={'entry': 'Manual entry'})
            expire_events(g.db)
            g.db.commit()
            flash('Existing opportunity matched; source retained.' if duplicate else 'Opportunity added.', 'success')
            return redirect(url_for('opportunity_detail', identifier=opportunity.id))
        return render_template('opportunity_form.html', title='Add opportunity', opportunity=None, kind=request.args.get('kind', 'income'), text_fields=TEXT_FIELDS, number_fields=NUM_FIELDS, date_fields=DATE_FIELDS)

    @app.get('/opportunities/<int:identifier>')
    def opportunity_detail(identifier):
        opportunity = get_opportunity(identifier)
        return render_template('detail.html', title=opportunity.title, opportunity=opportunity, earnings=estimate(opportunity))

    @app.route('/opportunities/<int:identifier>/edit', methods=['GET', 'POST'])
    def edit_opportunity(identifier):
        opportunity = get_opportunity(identifier)
        if request.method == 'POST':
            data = dict(request.form)
            data['evidence'] = opportunity.evidence
            record = validate_record(data)
            for key, value in record.items():
                setattr(opportunity, key, value)
            opportunity.updated_at = utcnow()
            opportunity.score, opportunity.score_details = score(opportunity, g.settings)
            expire_events(g.db)
            g.db.commit()
            flash('Opportunity updated.', 'success')
            return redirect(url_for('opportunity_detail', identifier=identifier))
        return render_template('opportunity_form.html', title='Edit opportunity', opportunity=opportunity, kind=opportunity.kind, text_fields=TEXT_FIELDS, number_fields=NUM_FIELDS, date_fields=DATE_FIELDS)

    @app.post('/opportunities/<int:identifier>/status')
    def update_status(identifier):
        opportunity = get_opportunity(identifier)
        transition(opportunity, request.form.get('status'))
        if request.form.get('note', '').strip():
            add_note(opportunity, request.form['note'])
        expire_events(g.db)
        g.db.commit()
        flash('Status and history updated.', 'success')
        return redirect(url_for('opportunity_detail', identifier=identifier))

    @app.post('/opportunities/<int:identifier>/notes')
    def opportunity_note(identifier):
        add_note(get_opportunity(identifier), request.form.get('note', ''))
        g.db.commit()
        return redirect(url_for('opportunity_detail', identifier=identifier))

    @app.post('/opportunities/<int:identifier>/assessment')
    def assessment(identifier):
        opportunity = get_opportunity(identifier)
        evidence = {}
        for dimension in ('earning', 'fit', 'career'):
            value = request.form.get(dimension)
            reason = request.form.get(f'{dimension}_reason', '').strip()
            if value or reason:
                evidence[dimension] = dict(value=number(value, dimension, required=True), reason=reason)
        data = {key: getattr(opportunity, key) for key in (*TEXT_FIELDS, *NUM_FIELDS, *DATE_FIELDS, 'kind', 'remote', 'flexible', 'compensation_type', 'pay_basis')}
        data['evidence'] = evidence
        validate_record(data)
        opportunity.evidence = evidence
        opportunity.updated_at = utcnow()
        opportunity.score, opportunity.score_details = score(opportunity, g.settings)
        g.db.commit()
        return redirect(url_for('opportunity_detail', identifier=identifier))

    @app.route('/import', methods=['GET', 'POST'])
    def csv_import():
        if request.method == 'POST':
            upload = request.files.get('file')
            if not upload:
                raise ValueError('Choose a CSV file.')
            added, duplicates = import_csv(sessions, upload.read(), g.settings)
            flash(f'Imported {added} new opportunities; {duplicates} duplicates matched.', 'success')
            return redirect(url_for('overview'))
        return render_template('import.html', title='Import opportunities')

    @app.route('/contacts', methods=['GET', 'POST'])
    def contacts():
        if request.method == 'POST':
            identifier = request.form.get('id')
            contact = g.db.get(Contact, int(identifier)) if identifier else Contact()
            if not contact:
                abort(404)
            update_contact(contact, request.form, get_opportunity)
            g.db.add(contact)
            g.db.commit()
            flash('Contact saved. No message was sent.', 'success')
            return redirect(url_for('contacts'))
        records = list_records(g.db, Contact, [Contact.followup_at.asc().nulls_last(), Contact.name])
        editing = g.db.get(Contact, request.args.get('edit', type=int)) if request.args.get('edit') else None
        return render_template('contacts.html', title='Contacts & follow-ups', contacts=records, editing=editing,
                               opportunities=list_records(g.db, Opportunity, [Opportunity.title]))

    @app.route('/earnings', methods=['GET', 'POST'])
    def earnings_tracker():
        if request.method == 'POST':
            linked = request.form.get('opportunity_id')
            hours = number(request.form.get('hours'), 'Total hours', required=True)
            if hours <= 0:
                raise ValueError('Hours must be greater than zero.')
            date = parse_date(request.form.get('date'))
            if not date:
                raise ValueError('Earnings date is required.')
            g.db.add(Earning(opportunity_id=get_opportunity(int(linked)).id if linked else None,
                             date=date, hours=hours, gross=number(request.form.get('gross'), 'Gross amount', required=True),
                             expenses=number(request.form.get('expenses'), 'Expenses', required=True), notes=request.form.get('notes', '').strip()))
            g.db.commit()
            flash('Actual earnings recorded (user reported).', 'success')
            return redirect(url_for('earnings_tracker'))
        opportunities = list_opportunities(g.db, 'income')
        earnings = list_records(g.db, Earning, [Earning.date.desc()])
        return render_template('earnings.html', title='Income tracker', opportunities=opportunities, earnings=earnings,
                               income=income_summary(opportunities, earnings, g.settings))

    @app.get('/research')
    def research_runs():
        runs = all_runs()
        return render_template('research.html', title='Research runs', runs=runs[:200], health=provider_health(runs, research.providers, g.settings))

    @app.post('/research/run')
    def manual_research():
        kind = request.form.get('kind') or None
        if kind not in (None, 'income', 'network'):
            raise ValueError('Invalid research service.')
        lock = app.extensions['dispatch_lock']
        if lock.acquire(blocking=False):
            def execute():
                try:
                    research.run(kind)
                except Exception:
                    app.logger.exception('Research dispatch failed')
                finally:
                    lock.release()
            threading.Thread(target=execute, daemon=True, name='opportunityscout-research').start()
            flash('Research requested. Providers have a six-hour cooldown; refresh this page for results.', 'success')
        else:
            flash('Research is already running.', 'info')
        return redirect(url_for('research_runs'))

    @app.route('/settings', methods=['GET', 'POST'])
    def settings_page():
        if request.method == 'POST':
            try:
                updated = json.loads(request.form.get('settings', ''))
            except json.JSONDecodeError as exc:
                raise ValueError(f'Invalid settings JSON: {exc.msg}') from exc
            validate_settings(updated)
            path = Path(app.config['SETTINGS_PATH'])
            temporary = path.with_name(path.name + f'.{uuid4().hex}.tmp')
            try:
                temporary.write_text(json.dumps(updated, indent=2) + '\n')
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            research.maintenance()
            scheduler = app.extensions.get('scheduler')
            if scheduler:
                scheduler.configure()
            flash('Settings saved and scores refreshed. Scheduling changes apply immediately in the standard server.', 'success')
            return redirect(url_for('settings_page'))
        return render_template('settings.html', title='Settings', settings_json=json.dumps(g.settings, indent=2))

    @app.get('/api/opportunities')
    def api_opportunities():
        kind = request.args.get('kind', 'income')
        if kind not in ('income', 'network'):
            raise ValueError('Invalid kind.')
        return jsonify([serialize_opportunity(o) for o in filtered_opportunities(kind)])

    @app.route('/api/opportunities/<int:identifier>', methods=['GET', 'PATCH'])
    def api_opportunity(identifier):
        opportunity = get_opportunity(identifier)
        if request.method == 'PATCH':
            data = request.get_json()
            if not isinstance(data, dict) or not set(data) <= {'status', 'note'}:
                raise ValueError('API updates support status and note fields.')
            if 'status' in data:
                transition(opportunity, data['status'])
            if 'note' in data:
                if not isinstance(data['note'], str):
                    raise ValueError('Note must be text.')
                add_note(opportunity, data['note'])
            expire_events(g.db)
            g.db.commit()
        return jsonify(serialize_opportunity(opportunity))

    @app.get('/api/health')
    def api_health():
        health = provider_health(all_runs(), research.providers, g.settings)
        return jsonify(database='available', providers=[dict(name=h['name'], state=h['state'], last_success=h['last_success'].isoformat()+'Z' if h['last_success'] else None) for h in health])

    return app


def serialize_opportunity(opportunity):
    keys = ('id', 'kind', 'title', 'organization', 'location', 'category', 'remote', 'status', 'url', 'compensation_text', 'compensation_type', 'pay_basis', 'amount', 'score', 'score_details')
    data = {key: getattr(opportunity, key) for key in keys}
    for key in ('first_seen', 'last_seen', 'last_verified', 'event_start', 'event_end'):
        value = getattr(opportunity, key)
        data[key] = value.isoformat()+'Z' if value else None
    data['sources'] = [dict(provider=s.provider, url=s.url, source_id=s.source_id) for s in opportunity.sources]
    data['estimated_hourly'] = estimate(opportunity).hourly
    return data
