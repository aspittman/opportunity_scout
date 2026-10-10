"""Expense-adjusted comparisons, explicitly before any unknown taxes."""
from dataclasses import dataclass


@dataclass
class EarningsEstimate:
    hourly: float | None
    missing: list[str]
    assumptions: list[str]
    total_hours: float | None = None
    net_amount: float | None = None


def estimate(record):
    def get(key):
        return record.get(key) if isinstance(record, dict) else getattr(record, key, None)
    missing = []
    assumptions = ['Expenses are user estimates; taxes and benefits are not calculated.',
                   'Employee wages, contractor receipts, and rideshare net income are not directly equivalent.']
    amount, hours, mode = get('amount'), get('work_hours'), get('compensation_type')
    if amount is None:
        missing.append('Compensation amount')
    if get('pay_basis') not in ('employee_gross', 'contractor_gross', 'reported_net'):
        missing.append('Employee / contractor / reported net compensation basis')
    if hours is None or hours <= 0:
        missing.append('Work hours for the comparison period')
    for key, label in [('travel_hours', 'Unpaid travel time'), ('preparation_hours', 'Unpaid preparation time'), ('expenses', 'Transportation and supplies expenses')]:
        if get(key) is None:
            missing.append(label)
    if get('kind') == 'network' and get('admission_cost') is None:
        missing.append('Admission cost')
    annual_hours = get('annual_hours')
    if mode == 'salary' and (annual_hours is None or annual_hours <= 0):
        missing.append('Annual paid hours for salary conversion')
    if mode not in ('hourly', 'salary', 'fixed'):
        missing.append('Compensation period/type')
    if missing:
        return EarningsEstimate(None, missing, assumptions)
    gross = amount * hours if mode == 'hourly' else amount * hours / annual_hours if mode == 'salary' else amount
    total = hours + get('travel_hours') + get('preparation_hours')
    costs = get('expenses') + (get('admission_cost') or 0)
    net = gross - costs
    assumptions.append('Travel, preparation, and expenses apply to the same period as work hours; admission is separate from expenses.')
    return EarningsEstimate(round(net / total, 2), [], assumptions, total, net)


def income_summary(opportunities, earnings, settings):
    weekly = 0.0
    hours = 0.0
    unknown = 0
    for opportunity in opportunities:
        if opportunity.kind != 'income' or opportunity.status != 'Active':
            continue
        result = estimate(opportunity)
        if result.hourly is None or not opportunity.weekly_hours or opportunity.compensation_type == 'fixed':
            unknown += 1
            continue
        # weekly_hours means paid/work hours, not travel-inclusive hours.
        time = opportunity.weekly_hours * result.total_hours / opportunity.work_hours
        weekly += result.hourly * time
        hours += time
    baseline_weekly = settings['baseline_hourly'] * settings['weekly_availability']
    return dict(projected_weekly=weekly, projected_monthly=weekly * 52 / 12,
                required_hours=hours, progress=100 * weekly / baseline_weekly if baseline_weekly else 0,
                baseline_weekly=baseline_weekly, unestimated=unknown,
                verified_gross=sum(e.gross for e in earnings),
                verified_net=sum(e.gross-e.expenses for e in earnings),
                verified_hours=sum(e.hours for e in earnings))
