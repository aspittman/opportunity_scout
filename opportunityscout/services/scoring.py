"""Evidence-based ranking, never statistical probabilities."""
from .earnings import estimate


def score(record, settings):
    def get(key, default=None):
        value = record.get(key, default) if isinstance(record, dict) else getattr(record, key, default)
        return default if value is None else value
    kind = get('kind', 'income')
    evidence = get('evidence', {})
    dimensions = dict.fromkeys(('earning', 'fit', 'flexibility', 'travel', 'career'), 20.0)
    reasons, penalties, missing = [], [], []
    earnings = estimate(record)
    if kind == 'income':
        if earnings.hourly is None:
            missing.extend(earnings.missing)
            penalties.append('Earning potential remains conservative until compensation and costs are documented.')
        else:
            net = earnings.hourly
            dimensions['earning'] = 100 if net >= settings['preferred_hourly'] else 75 if net >= settings['minimum_hourly'] else 45 if net >= settings['baseline_hourly'] else 15
            reasons.append(f'Expense-adjusted rate ${net:.2f}/h before unknown taxes; preferred target ${settings["preferred_hourly"]:.2f}/h.')
    else:
        if not evidence.get('earning'):
            missing.append('Employment and business conversion value are unverified unless documented in assessment evidence.')
    # Explicit assessments are human judgments supported by user-supplied notes.
    for key in ('earning', 'fit', 'career'):
        assessment = evidence.get(key)
        if isinstance(assessment, dict) and assessment.get('reason') and isinstance(assessment.get('value'), (int, float)):
            if kind == 'income' and key == 'earning':
                continue
            dimensions[key] = max(0, min(100, assessment['value']))
            reasons.append(f'{key.title()} assessment (user judgment): {assessment["reason"]}')
        elif key != 'earning':
            text = ' '.join(str(get(x, '')) for x in ('title', 'category', 'industries')).lower()
            terms = settings['preferred_categories'] if key == 'fit' else settings['preferred_industries']
            matches = [x for x in terms if x.lower() in text]
            if matches:
                dimensions[key] = 60
                reasons.append(f'{key.title()} recommendation inferred from matching terms: {", ".join(matches)}. Suitability is not verified.')
            else:
                missing.append(f'{key.title()} evidence')
    if get('flexible') is True:
        dimensions['flexibility'] = 90
        reasons.append('Flexible schedule explicitly recorded.')
    elif get('flexible') is False:
        dimensions['flexibility'] = 25
        penalties.append('Schedule explicitly marked inflexible.')
    elif get('arrangement', '') in settings['preferred_arrangements']:
        dimensions['flexibility'] = 55
        reasons.append('Preferred work arrangement; actual schedule remains unverified.')
        missing.append('Schedule flexibility')
    else:
        missing.append('Schedule flexibility')
    if get('weekly_hours') and get('weekly_hours') > settings['weekly_availability']:
        dimensions['flexibility'] = min(dimensions['flexibility'], 10)
        penalties.append('Required weekly hours exceed configured availability.')
    if get('remote') is True:
        dimensions['travel'] = 100
        reasons.append('Remote listing; no commute assumed for ranking only.')
        if not settings['remote_preference']:
            dimensions['travel'] = 60
    elif get('distance_miles') is not None:
        distance = get('distance_miles')
        dimensions['travel'] = max(0, 85 - distance / settings['travel_radius_miles'] * 60)
        reasons.append(f'User-estimated travel distance: {distance:g} miles; radius preference {settings["travel_radius_miles"]:g} miles.')
        if distance > settings['travel_radius_miles']:
            penalties.append('Beyond preferred travel radius.')
    else:
        missing.append('Travel distance/time')
    if kind == 'network':
        if not get('event_start'):
            missing.append('Event date/time')
        if get('admission_cost') is None:
            missing.append('Admission cost')
        if not get('organization'):
            missing.append('Organizer')
    weights = settings[f'{kind}_weights']
    total = round(sum(dimensions[key]*weights[key]/100 for key in dimensions), 1)
    if len(set(missing)) >= 4:
        total = min(total, 65)
        penalties.append('Score capped at 65 because four or more evidence fields are missing.')
    return total, dict(dimensions=dimensions, weights=weights, reasons=reasons, penalties=penalties,
                       missing=sorted(set(missing)), label='Heuristic ranking; not a probability of success.')
