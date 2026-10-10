import pytest
from opportunityscout.services.earnings import estimate, income_summary
from opportunityscout.services.scoring import score
from opportunityscout.database.models import Earning, Opportunity
from opportunityscout.services.validation import validate_record


def test_income_scoring_explains_weighted_result(paid_record, settings):
    value, details = score(paid_record, settings)
    assert value == pytest.approx(95.75, abs=.1)
    assert details['dimensions']['earning'] == 100
    assert details['reasons']
    assert details['label'].endswith('not a probability of success.')
    assert 0 <= value <= 100


def test_network_scoring_is_a_separate_model(settings):
    record = dict(kind='network', title='Professional networking fixture', organization='Fixture organizer',
                  event_start='2027-01-20T12:00:00-07:00', admission_cost=0, flexible=True, remote=True,
                  evidence={key: dict(value=value, reason='Human review with supporting context') for key, value in [('earning', 80), ('fit', 90), ('career', 95)]})
    value, details = score(record, settings)
    assert value == pytest.approx(90.8, abs=.1)
    assert details['weights']['career'] == 35
    assert 'Employment and business conversion value' not in ' '.join(details['missing'])


def test_unknown_pay_does_not_get_high_score(settings):
    value, details = score({'kind': 'income', 'title': 'Unknown job', 'remote': True}, settings)
    assert value < 50
    assert 'Compensation amount' in details['missing']
    assert any('conservative' in penalty for penalty in details['penalties'])
    assert estimate({'kind': 'income'}).hourly is None


def test_missing_costs_are_not_assumed_zero(paid_record):
    paid_record['expenses'] = None
    result = estimate(paid_record)
    assert result.hourly is None
    assert 'Transportation and supplies expenses' in result.missing


def test_fixed_fee_uses_expenses_and_all_time(paid_record):
    paid_record.update(compensation_type='fixed', amount=500, work_hours=10, travel_hours=2, preparation_hours=3, expenses=50)
    result = estimate(paid_record)
    assert result.hourly == 30
    assert result.total_hours == 15
    assert result.net_amount == 450


def test_salary_requires_annual_hours(paid_record):
    paid_record.update(compensation_type='salary', amount=52000, pay_basis='employee_gross')
    assert estimate(paid_record).hourly is None
    paid_record['annual_hours'] = 2080
    assert estimate(paid_record).hourly == 25


def test_event_admission_is_an_expense(paid_record):
    paid_record.update(kind='network', amount=200, compensation_type='fixed', admission_cost=50)
    assert estimate(paid_record).hourly == 15


def test_low_pay_retained_with_career_value(paid_record, settings):
    paid_record['amount'] = 18
    value, details = score(paid_record, settings)
    assert value > 0
    assert details['dimensions']['career'] == 80
    assert details['dimensions']['earning'] == 15


def test_availability_penalty(paid_record, settings):
    paid_record['weekly_hours'] = settings['weekly_availability'] + 10
    _, details = score(paid_record, settings)
    assert any('exceed' in penalty for penalty in details['penalties'])


def test_custom_weights_change_ranking(paid_record, settings):
    settings['income_weights'] = dict(earning=100, fit=0, flexibility=0, travel=0, career=0)
    assert score(paid_record, settings)[0] == 100


def test_projected_income_excludes_fixed_fee_and_unknowns(paid_record, settings):
    recurring = Opportunity(**validate_record(paid_record), status='Active')
    fixed = Opportunity(**validate_record({**paid_record, 'compensation_type': 'fixed'}), status='Active')
    result = income_summary([recurring, fixed], [Earning(gross=100, expenses=10, hours=5)], settings)
    assert result['projected_weekly'] == 500
    assert result['unestimated'] == 1
    assert result['verified_net'] == 90
    assert result['projected_monthly'] == pytest.approx(500*52/12)


def test_weekly_projection_includes_unpaid_time(paid_record, settings):
    paid_record.update(travel_hours=2, preparation_hours=3, expenses=50)
    opportunity = Opportunity(**validate_record(paid_record), status='Active')
    result = income_summary([opportunity], [], settings)
    assert result['required_hours'] == 15
    assert result['projected_weekly'] == 450
