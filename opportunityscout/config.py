"""Validated local configuration; no external application dependencies."""
import json
import math
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')
DEFAULTS = json.loads((ROOT / 'opportunityscout/default_settings.json').read_text())


def validate_settings(settings):
    if not isinstance(settings, dict) or set(settings) != set(DEFAULTS):
        raise ValueError('Settings must contain exactly the documented keys.')
    for key in ('baseline_hourly', 'minimum_hourly', 'preferred_hourly', 'weekly_availability', 'travel_radius_miles', 'income_interval_hours', 'network_interval_hours'):
        value = settings[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{key} must be a positive finite number.')
    if settings['minimum_hourly'] > settings['preferred_hourly']:
        raise ValueError('Minimum target cannot exceed preferred target.')
    if settings['income_interval_hours'] < 6 or settings['network_interval_hours'] < 6:
        raise ValueError('Research intervals must be at least six hours.')
    for key in ('locations', 'preferred_categories', 'preferred_industries', 'preferred_arrangements', 'enabled_providers'):
        if not isinstance(settings[key], list) or not all(isinstance(x, str) and x.strip() for x in settings[key]):
            raise ValueError(f'{key} must be a list of nonempty strings.')
    if not set(settings['enabled_providers']) <= {'remotive', 'utah_tech_calendar'}:
        raise ValueError('Unknown provider.')
    for key in ('remote_preference', 'income_enabled', 'network_enabled'):
        if not isinstance(settings[key], bool):
            raise ValueError(f'{key} must be true or false.')
    for key in ('income_weights', 'network_weights'):
        weights = settings[key]
        if not isinstance(weights, dict) or set(weights) != {'earning', 'fit', 'flexibility', 'travel', 'career'}:
            raise ValueError(f'{key} has invalid dimensions.')
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in weights.values()) or abs(sum(weights.values()) - 100) > .001:
            raise ValueError(f'{key} must be nonnegative and total 100.')
    return settings


def load_settings(path=None):
    path = Path(path or os.getenv('OPPORTUNITYSCOUT_SETTINGS', ROOT / 'settings.json'))
    return validate_settings(json.loads(path.read_text()))
