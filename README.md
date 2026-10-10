# OpportunityScout — Version 1

A standalone local Python application for discovering better income opportunities and building professional connections. Flask, SQLite, SQLAlchemy, and a lightweight background scheduler. No CRM integration, cloud service, automatic applications, event registration, or outreach.

## Quick start on Linux Mint

Requires Python **3.11+** (tested with 3.12). Run from this directory:

```bash
cd /home/aaron/MyBotz/opportunity_scout
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python main.py init-db
python main.py serve
```

Open **http://127.0.0.1:5000**. Stop with Ctrl+C. Database creation is automatic when the app starts; `init-db` is an explicit, repeatable initialization command, not a reset.

If you already installed this project's environment with uv, use it directly:

```bash
.venv/bin/python main.py init-db
.venv/bin/python main.py serve
```

If Python 3.11+ is missing, uv can install a separate interpreter without replacing Mint's system Python ([official uv instructions](https://docs.astral.sh/uv/getting-started/installation/)):

```bash
curl -LsSf https://astral.sh/uv/install.sh -o /tmp/uv-install.sh
sh /tmp/uv-install.sh
"$HOME/.local/bin/uv" python install 3.12
"$HOME/.local/bin/uv" venv --python 3.12 .venv
"$HOME/.local/bin/uv" pip install --python .venv/bin/python -r requirements.txt
```

No environment variables or API keys are required. Copying `.env.example` is optional. Startup launches due research in the background and starts scheduling. An empty database shows useful empty states, never fictional leads. Provider failures are recorded in Research Runs and do not stop the dashboard.

## What is implemented

- Responsive dashboard with sidebar, overview totals, prioritized recommendations, service health, and income replacement progress.
- Searchable income listings with category, location, work mode, source, status, and score filters.
- Networking events in list or calendar agenda view, local dates, source registration links, admission cost when supplied, and organizer/audience/value fields.
- Manual entry and editing, atomic UTF-8 CSV import, source deduplication, source snapshots, first/last seen timestamps.
- Separate transparent income and networking scoring models with dimensions, weights, reasons, penalties, and missing information.
- All requested lifecycle statuses, immutable status-change history, dated notes, and automatic event expiration.
- Manual contacts and follow-up dates with opportunity association and relationship status. No messages are sent.
- Expense-adjusted hourly estimates, recurring weekly/monthly projections for active work, and actual earnings recorded separately by the user.
- Modular public job and event adapters, bounded HTTP retries, timeouts, robots enforcement where applicable, persistent provider cooldowns, process locks, and durable execution history.
- Validated settings editor, local read API, status/note API updates with CSRF protection.

## Research providers and access limitations

### Remotive — public job API

Endpoint: `https://remotive.com/api/remote-jobs`.

[Official API documentation and terms](https://github.com/remotive-com/remote-jobs-api) document free access. Listings retain Remotive attribution and link to the original Remotive listing. Data is delayed by 24 hours; the publisher recommends no more than four requests per day. The application enforces a **minimum six-hour interval** for all calls, including manual calls and failed runs. HTTP status 429 is recorded as a failure without retrying. Server/transient failures may retry twice with backoff.

Only records explicitly listing US, USA, United States, worldwide, anywhere, or global eligibility are accepted. Region descriptions are not a legal eligibility determination: check citizenship, state exclusions, and other conditions yourself. Turning off `remote_preference` disables acceptance of these remote listings. Categories influence ranking, rather than discarding all nontechnical jobs.

Salary text is preserved verbatim as plain text. The adapter **does not infer a pay period, currency conversion, tax-adjusted rate, or paid hours** from salary strings. Fill in compensation type, basis, amount, hours, and expenses when you have reliable information. Job closing dates are often unavailable; lack of a job in a later feed does not automatically mark it expired. Do not republish this private dataset to third-party job boards.

### Utah Tech Calendar — published iCalendar feed

Endpoint: `https://utahtechcalendar.com/api/ical`, discovered from the calendar's published subscribe link ([calendar](https://utahtechcalendar.com/)). Uses the `icalendar` library for folded text, time zones, and date-only events. The provider checks `robots.txt` before requesting the feed. A 404 robots file permits the published feed; denied access, authentication, unexpected redirects, or robots retrieval failures stop the run. It never bypasses restrictions.

Accepts venues matching configured county/city terms. Unknown venues are retained for review; there is no geocoding or travel-distance inference. Tech scope is reflected in explicitly inferred audience/industry descriptions. Organizer, admission, hiring activity, and connection value stay unknown unless the source or user supplies them. No attendance numbers are invented. Always confirm time, venue, cost, and registration with the organizer before traveling. Recurrence rules and cancelled VEVENTs are skipped and explained in run errors; explicit dated occurrences work. Provider access policies or feed formats may change.

**Verification:** Both adapters have deterministic normalization/retrieval tests. The calendar publishes the feed link and Remotive documents the API, but live requests could not be verified from the development sandbox because DNS/network access is restricted. Actual live ingestion is therefore not claimed as tested. Run `python main.py research` from a network-enabled terminal and inspect Research Runs. If either provider is unavailable, manual entry and CSV remain fully functional. Local Utah job boards and chamber/business calendars are future adapters; V1's automatic job provider covers remote work and the event provider focuses on tech networking.

### Adding a provider

Implement `Provider.fetch()`, `normalize(raw)`, and optional `accepts(record, settings)` in `opportunityscout/providers/`. Return explicit normalized facts, including a stable `source_id`. Register in `default_providers()` and update settings validation. Consult the source's official documented API/feed and terms first. Do not invent endpoints or add a restricted scraper.

## Scheduling and commands

```bash
python main.py serve                     # Dashboard, startup research, background scheduling
python main.py init-db                   # Create missing tables, preserve existing data
python main.py research                  # Both enabled scouts; six-hour cooldown applies
python main.py research --kind income    # Income only
python main.py research --kind network   # Network only
python main.py maintain                  # Expire events and refresh scores
python main.py serve --no-scheduler --no-startup-research
python -m pytest -q                      # Deterministic tests; no live internet needed
```

An APScheduler dispatcher checks every five minutes whether each provider is due according to its scout's configurable frequency. Default: income and networking every 24 hours. Durable start times and a filesystem lock prevent overlapping research across processes; a separate scheduler lock ensures a single owner. Expiration/scoring maintenance also runs every 24 hours and expiration checks run when viewing the dashboard. Scoring refreshes after ingestion, edits, or settings changes. Settings changes take effect immediately in the standard `main.py serve` process.

The dashboard Run Research button dispatches background work, respecting cooldowns. Refresh the Research Runs page to see completion. Simultaneous requests are coalesced or rejected as already running. A crashed Running record becomes Interrupted when the next research process obtains the exclusive lock. A Running record over 30 minutes is shown as Stalled. Provider health uses the latest execution and freshness (1.5 times the configured interval); an old successful execution cannot hide a newer failure. Partial runs are not Healthy.

## Configuration and environment

Edit `settings.json` or the dashboard Settings page. Includes preferred categories/industries/arrangements, target county/city terms, remote preference, travel radius, weekly availability, hourly targets, separate weights, scout enable flags, provider enable list, and research frequency. Weights must be nonnegative and sum to 100. Intervals must be at least six hours. No automatic outreach switch exists because no outreach functionality exists.

Defaults: Utah County and Salt Lake County cities; remote US/worldwide listings; $19/h rideshare net baseline, $25/h minimum target, $35/h preferred target; 30 available hours/week; 35-mile preferred travel radius. The latter two are editable planning assumptions, not facts about the user.

All environment variables are optional:

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPPORTUNITYSCOUT_DATABASE` | `data/opportunityscout.db` | SQLite file; relative paths use project root |
| `OPPORTUNITYSCOUT_SETTINGS` | `settings.json` | Editable JSON file; relative paths use project root |
| `OPPORTUNITYSCOUT_SECRET_KEY` | Random per process | Set a long random value for stable browser sessions; otherwise sessions reset at restart |
| `OPPORTUNITYSCOUT_PORT` | `5000` | Local dashboard port |

The server binds `127.0.0.1` with debug/reloader disabled. `.env`, database files, local data, and the virtual environment are excluded from Git. Contacts remain local. External links permit only HTTP(S), exclude embedded credentials, and use `noopener noreferrer`. Requests require localhost Host headers; all mutations require same-origin CSRF tokens. HTML autoescaping and a self-only content security policy are enabled. This is a single-user local development server, not a public hosting configuration.

## Earnings and scoring assumptions

Hourly: `amount × paid work hours`. Salary: `annual amount × comparison-period paid hours ÷ annual paid hours`. Fixed fee: the entire project amount. Then:

```text
expense-adjusted hourly = (compensation − transport/supplies expenses − admission)
                          ÷ (paid/project hours + unpaid travel + unpaid preparation)
```

All inputs apply to the same comparison period. Blank time/cost inputs remain unknown; enter zero only when confirmed. Estimates require an explicit employee gross / contractor gross / reported net basis. Enter compensation before the opportunity-specific expenses entered in the form, to avoid subtracting them twice. Taxes and benefits are not inferred. Employee wages, contractor revenue, and rideshare net are labeled and are not assumed equivalent.

Recurring projections include only Active hourly/salary work with complete estimates and recurring paid weekly hours. Fixed projects are excluded from recurring totals. Weekly unpaid time/costs are scaled from the comparison period. Monthly = weekly × 52 ÷ 12. Actual earnings are separately user-reported payments and expenses, not externally audited. Income replacement compares projected expense-adjusted income with the configured rideshare net baseline and hours; it is a planning indicator, not take-home tax advice.

Income weights: earning 35, fit 25, flexibility 20, travel 15, career 5. Networking: earning 20, usefulness 25, flexibility 10, travel 10, career 35. Assessments use explicit facts or clearly labeled term matches. You may record your own 0–100 fit/career/connection value with written evidence. These are judgments, never statistical probabilities. Missing earning inputs start conservatively, and four or more missing fields cap the result at 65. High priority begins at 75. Lower-paid leads remain stored and can rank usefully through career/flexibility value.

## Import and data quality

CSV upload accepts up to 2 MB / 2,000 rows. `title` is required; the dashboard Import page documents every supported column and value. Invalid rows reject the entire import. Imported status starts New. Use a stable `source_id` for repeat imports of updated source snapshots. Without it, a deterministic identity is generated. Blank booleans/numbers represent unknowns. Dates with offsets are respected; input strings without offsets use America/Denver. SQLite timestamps are UTC and dashboard dates use Mountain time.

Deduplication uses provider/source IDs first, then normalized URLs plus title (and event date), or exact normalized title/company/location (and event date). Tracking URL parameters and fragments are ignored; identifying query parameters are preserved. Different event dates stay separate. Multiple possible matches never merge automatically. Source snapshots are retained, while provider refreshes preserve manually edited opportunity fields and workflow state. Review fresh snapshots for changed facts; automatic field reconciliation is not in V1. “Last source retrieval” establishes feed retrieval, not independent fact verification.

## API

- `GET /api/opportunities?kind=income` or `kind=network`; supports dashboard search/filter parameters.
- `GET /api/opportunities/<id>` includes sources, score explanations, UTC dates, and estimated hourly value.
- `PATCH /api/opportunities/<id>` accepts `status` and/or `note` only.
- `GET /api/health` reports database availability and provider-specific states/last success.

API mutation requires the browser session cookie and the token from the page's `csrf-token` meta tag in `X-CSRF-Token`. This is deliberately a local browser API; there is no unauthenticated outreach/action endpoint. Manual creation, editing, contacts, earnings, CSV, and research run forms use the same CSRF protections.

## Project structure

```text
app.py                        Flask factory entry point
main.py                       Local CLI and scheduler owner
settings.json                 User configuration
requirements.txt              Dependency ranges
requirements.lock.txt         Exact tested dependency versions
opportunityscout/
  app.py                      Dashboard/API request handling
  config.py                   Settings validation and environment
  default_settings.json       Immutable shipped default schema
  database/
    models.py                 Opportunities, provenance, history, contacts, earnings, runs
    repository.py             Persistence, queries, deduplication, lifecycle, expiration
  providers/
    base.py                   Provider interface and polite HTTP client
    remotive.py               Remote public job adapter
    utah_calendar.py          Public event iCalendar adapter
  services/
    research.py               Income/network orchestration and health reporting
    scheduler.py              Local single-owner due-time dispatcher
    scoring.py                Independent transparent ranking models
    earnings.py               Expense-adjusted estimates and income projection
    contacts.py               Manual relationship validation
    deduplication.py          Conservative identity matching and URL safety
    importing.py              Atomic CSV ingestion
    validation.py             Shared opportunity input normalization
  templates/                  Responsive HTML dashboard
  static/                     CSS and small progressive JS enhancement
tests/                        Offline service/provider/storage/dashboard/security checks
data/                         Ignored local database and process locks
```

## Tests and known limitations

Verified result: **70 tests passed on Python 3.12**. Run `.venv/bin/python -m pytest -q`. Tests cover income/network weights, unknown pay/costs, hourly/project/salary earnings, recurring versus actual earnings, deduplication and ambiguous matches, persistence, status/notes history, expiration, time zones, provider normalization, malformed/failed feeds, partial-run counters, freshness, cooldowns, process locks, CSV atomicity, dashboard forms/API, filters, settings, and request security. Live internet is never required. The development sandbox also blocks listening sockets; dashboard behavior was verified through Flask’s WSGI test client, and localhost/debug/reloader CLI settings are tested. Launch the real server from your regular terminal. For the exact tested dependencies, install `requirements.lock.txt` instead of `requirements.txt`.

Version 1 does not include geographic route calculations, recurrence expansion, resume matching, tax calculations, AI analysis, automatic contacts, messaging, registration, applications, notifications, public hosting, or authentication for multiple users. The agenda groups events by date; it is not a drag-and-drop monthly calendar. The dashboard loads local records without pagination and source matching scans same-kind records; suitable for a personal V1 dataset. SQLite tables are created automatically; formal schema migrations are a V2 concern. Back up the database before future upgrades. Do not commit a database containing personal data. No demo data command is supplied because the real empty states and manual-entry workflow work without fabricated listings.

## Recommended Version 2

1. Add permitted local job feeds/company career adapters, Utah workforce listings, and chamber/business calendars.
2. Improve source change review and expiry verification, add indexed deduplication and pagination.
3. Add user-approved resume/skills matching and recommendation feedback with historical conversion metrics.
4. Add calendar export, local follow-up reminders, and opt-in notifications.
5. Add geographic travel estimates and recurring contract identification.
6. Add schema migrations and backup/restore controls before expanding storage.
