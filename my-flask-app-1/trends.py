"""Choices, checking and summaries for the progress charts (no database or web code here)."""
from collections import namedtuple

DAY_CHOICES = (7, 14, 30, 90, 180, 365)
DEFAULT_DAYS = 7

# key used in the data, name in the URL, label, unit, line color
Stat = namedtuple('Stat', 'key slug label unit color')
STATS = (
    Stat('calories', 'calories', 'Calories', 'kcal', '#e4572e'),
    Stat('protein_g', 'protein', 'Protein', 'g', '#2e86de'),
    Stat('carbs_g', 'carbs', 'Carbs', 'g', '#d99a00'),
    Stat('fat_g', 'fat', 'Fat', 'g', '#7d5ba6'),
)
STAT_CHOICES = (('all', 'All statistics'),) + tuple((s.slug, s.label) for s in STATS)


def parse_trend_params(args):
    """(days, stat) from the page's query string. Anything unrecognised falls back to the defaults
    (7 days, all statistics) instead of showing an error."""
    try:
        days = int(args.get('days', DEFAULT_DAYS))
    except (TypeError, ValueError):
        days = DEFAULT_DAYS
    if days not in DAY_CHOICES:
        days = DEFAULT_DAYS
    stat = args.get('stat', 'all')
    if stat not in {slug for slug, _ in STAT_CHOICES}:
        stat = 'all'
    return days, stat


def _number(value, unit):
    """1,234 kcal / 12.3 g."""
    return f'{value:,.0f} {unit}' if unit == 'kcal' else f'{value:,.1f} {unit}'


def _short_date(day):
    return f'{day:%b} {day.day}'


def build_charts(rows, stat='all'):
    """One chart description per selected statistic, from get_rolling_data() rows.

    A day with nothing logged is left as a gap (None) rather than plotted as zero, since eating
    nothing and not logging are different things. The average, highest day and summary text are
    over the days that were logged.
    """
    charts = []
    for s in STATS:
        if stat not in ('all', s.slug):
            continue
        logged = [(row['date'], row[s.key]) for row in rows if row['logged']]
        average = sum(value for _, value in logged) / len(logged) if logged else None
        highest = max(logged, key=lambda pair: pair[1]) if logged else None
        if logged:
            summary = (f'Average {_number(average, s.unit)} per logged day. '
                       f'Highest {_number(highest[1], s.unit)} on {_short_date(highest[0])}. '
                       f'{len(logged)} of {len(rows)} days logged.')
        else:
            summary = 'Nothing logged in this period.'
        charts.append({
            'key': s.key, 'slug': s.slug, 'label': s.label, 'unit': s.unit, 'color': s.color,
            'labels': [row['date'].isoformat() for row in rows],
            'values': [round(row[s.key], 1) if row['logged'] else None for row in rows],
            'average': None if average is None else round(average, 1),
            'summary': summary,
        })
    return charts
