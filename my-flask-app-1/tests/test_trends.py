"""Run with:  python -m unittest discover -v   (from the project folder)"""
import unittest
from datetime import date, timedelta

from flask import Flask
from sqlalchemy import event

from models import MealItem, MealLog, User, db
from nutrition import get_daily_totals, get_rolling_average, get_rolling_data
from trends import DAY_CHOICES, STAT_CHOICES, build_charts, parse_trend_params

TODAY = date.today()


def days_ago(n):
    return TODAY - timedelta(days=n)


class RollingDataTests(unittest.TestCase):
    """get_rolling_data, against a throwaway in-memory database."""

    def setUp(self):
        self.app = Flask('trend-tests')
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        db.init_app(self.app)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        for n in (1, 2):
            db.session.add(User(id=n, username=f'user{n}', email=f'u{n}@x.com', password_hash='x'))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()

    def log(self, user, day, *items):
        """Log foods (calories, protein, carbs, fat) for a user on a day."""
        meal = MealLog(user_id=user, date=day)
        db.session.add(meal)
        db.session.flush()
        for n, (cal, pro, carb, fat) in enumerate(items):
            db.session.add(MealItem(meal_log_id=meal.id, food_name=f'food{n}', fdc_id=n, quantity_g=100,
                                    calories=cal, protein_g=pro, carbs_g=carb, fat_g=fat))
        db.session.commit()

    def test_one_entry_per_day_oldest_first_ending_today(self):
        for days in (1, 2, 7, 30, 365):
            data = get_rolling_data(1, days)
            dates = [row['date'] for row in data]
            self.assertEqual(len(data), days)
            self.assertEqual((dates[0], dates[-1]), (days_ago(days - 1), TODAY))
            self.assertEqual(dates, [days_ago(days - 1 - i) for i in range(days)])      # consecutive, no gaps or repeats

    def test_days_with_nothing_logged_are_zeros_and_marked_unlogged(self):
        data = get_rolling_data(1, 3)
        self.assertTrue(all(not row['logged'] for row in data))
        self.assertTrue(all(row[k] == 0 for row in data for k in ('calories', 'protein_g', 'carbs_g', 'fat_g')))

    def test_totals_add_up_the_days_items_and_land_on_the_right_day(self):
        self.log(1, TODAY, (500, 20, 60, 10), (300, 5, 40, 2.5))
        self.log(1, days_ago(2), (700, 30, 80, 25))
        data = get_rolling_data(1, 4)                       # days ago: 3, 2, 1, 0
        self.assertEqual([r['logged'] for r in data], [False, True, False, True])
        self.assertEqual((data[3]['calories'], data[3]['protein_g'], data[3]['carbs_g'], data[3]['fat_g']), (800, 25, 100, 12.5))
        self.assertEqual((data[1]['calories'], data[1]['protein_g'], data[1]['carbs_g'], data[1]['fat_g']), (700, 30, 80, 25))

    def test_today_is_included_and_days_just_outside_the_window_are_not(self):
        self.log(1, days_ago(6), (100, 1, 1, 1))              # the first day of a 7-day window
        self.log(1, days_ago(7), (900, 9, 9, 9))              # one day too old
        self.log(1, TODAY + timedelta(days=1), (800, 8, 8, 8))  # tomorrow
        data = get_rolling_data(1, 7)
        self.assertEqual([r['calories'] for r in data], [100, 0, 0, 0, 0, 0, 0])
        self.assertEqual(get_rolling_data(1, 8)[0]['calories'], 900)     # widening the window picks the old day up
        self.assertEqual(get_rolling_data(1, 1)[0]['date'], TODAY)

    def test_only_the_requested_users_data(self):
        self.log(1, TODAY, (500, 20, 60, 10))
        self.log(2, TODAY, (1500, 90, 160, 70))
        self.assertEqual(get_rolling_data(1, 1)[0]['calories'], 500)
        self.assertEqual(get_rolling_data(2, 1)[0]['calories'], 1500)
        self.assertFalse(get_rolling_data(99, 1)[0]['logged'])

    def test_missing_nutrient_values_count_as_zero(self):
        self.log(1, TODAY, (500, None, None, None), (100, 4, None, 1))
        row = get_rolling_data(1, 1)[0]
        self.assertEqual((row['calories'], row['protein_g'], row['carbs_g'], row['fat_g'], row['logged']), (600, 4, 0, 1, True))

    def test_a_log_with_no_items_is_not_a_logged_day(self):
        db.session.add(MealLog(user_id=1, date=TODAY))
        db.session.commit()
        self.assertFalse(get_rolling_data(1, 1)[0]['logged'])

    def test_agrees_with_the_daily_totals_and_the_average(self):
        for n, cal in ((0, 500), (1, 700), (3, 900), (5, 200), (9, 1200)):
            self.log(1, days_ago(n), (cal, cal / 10, cal / 5, cal / 20))
        data = get_rolling_data(1, 10)
        for row in data:
            totals = get_daily_totals(1, row['date'])
            self.assertEqual((row['calories'], row['protein_g'], row['carbs_g'], row['fat_g']),
                             (totals['calories'], totals['protein_g'], totals['carbs_g'], totals['fat_g']), row['date'])
        average = get_rolling_average(1, 10)
        for key in ('calories', 'protein_g', 'carbs_g', 'fat_g'):
            self.assertAlmostEqual(sum(row[key] for row in data) / 10, average[key])

    def test_a_year_costs_one_query_not_one_per_day(self):
        self.log(1, TODAY, (500, 20, 60, 10))
        statements = []
        event.listen(db.engine, 'before_cursor_execute', lambda *args: statements.append(args[2]))
        get_rolling_data(1, 365)
        self.assertEqual(len(statements), 1)

    def test_days_must_be_a_positive_whole_number(self):
        for bad in (0, -1):
            with self.assertRaises(AssertionError):
                get_rolling_data(1, bad)
        with self.assertRaises((AssertionError, TypeError)):
            get_rolling_data(1, 2.5)


class ParamTests(unittest.TestCase):
    def test_valid_choices_are_kept(self):
        for days in DAY_CHOICES:
            self.assertEqual(parse_trend_params({'days': str(days), 'stat': 'protein'}), (days, 'protein'))
        for slug, _ in STAT_CHOICES:
            self.assertEqual(parse_trend_params({'stat': slug})[1], slug)

    def test_the_offered_day_choices(self):
        self.assertEqual(DAY_CHOICES, (7, 14, 30, 90, 180, 365))

    def test_anything_else_falls_back_to_the_defaults(self):
        for args in ({}, {'days': 'abc'}, {'days': '8'}, {'days': '0'}, {'days': '-7'}, {'days': '7.5'}, {'days': ''},
                     {'days': '99999'}, {'stat': 'sugar'}, {'stat': ''}, {'stat': 'CALORIES'}, {'days': None}):
            self.assertEqual(parse_trend_params(args), (7, 'all'), args)
        self.assertEqual(parse_trend_params({'days': '8', 'stat': 'sugar'}), (7, 'all'))


def rows(*logged_values, total_days=None):
    """get_rolling_data-style rows: a value of None means that day wasn't logged."""
    total_days = total_days or len(logged_values)
    out = []
    for i in range(total_days):
        v = logged_values[i] if i < len(logged_values) else None
        out.append({'date': days_ago(total_days - 1 - i), 'logged': v is not None,
                    'calories': v or 0.0, 'protein_g': (v or 0.0) / 10, 'carbs_g': (v or 0.0) / 5, 'fat_g': (v or 0.0) / 20})
    return out


class BuildChartsTests(unittest.TestCase):
    def test_all_four_statistics_in_a_fixed_order(self):
        self.assertEqual([c['slug'] for c in build_charts(rows(1000, 2000))], ['calories', 'protein', 'carbs', 'fat'])

    def test_a_single_statistic(self):
        charts = build_charts(rows(1000, 2000), 'carbs')
        self.assertEqual([(c['slug'], c['label'], c['unit']) for c in charts], [('carbs', 'Carbs', 'g')])

    def test_unlogged_days_are_gaps_not_zeros(self):
        chart = build_charts(rows(1000, None, 3000))[0]
        self.assertEqual(chart['values'], [1000.0, None, 3000.0])
        self.assertEqual(len(chart['labels']), 3)
        self.assertIsNone(chart['values'][1])                              # a gap, which a chart draws as a break

    def test_labels_are_iso_dates_ending_today(self):
        chart = build_charts(rows(1, 2, 3))[0]
        self.assertEqual(chart['labels'], [days_ago(2).isoformat(), days_ago(1).isoformat(), TODAY.isoformat()])

    def test_average_and_summary_are_over_the_logged_days(self):
        chart = build_charts(rows(1000, None, 3000, None, None))[0]      # 2 of 5 days logged
        self.assertEqual(chart['average'], 2000.0)                         # (1000 + 3000) / 2, not / 5
        highest_day = days_ago(2)
        self.assertEqual(chart['summary'], f'Average 2,000 kcal per logged day. Highest 3,000 kcal on {highest_day:%b} {highest_day.day}. 2 of 5 days logged.')

    def test_grams_show_one_decimal(self):
        chart = build_charts(rows(1000, 2000), 'protein')[0]               # protein = calories / 10 in these rows
        self.assertEqual(chart['average'], 150.0)
        self.assertIn('Average 150.0 g per logged day.', chart['summary'])

    def test_nothing_logged(self):
        for chart in build_charts(rows(None, None, None)):
            self.assertEqual((chart['values'], chart['average'], chart['summary']), ([None, None, None], None, 'Nothing logged in this period.'))

    def test_a_logged_day_of_zero_is_data_not_a_gap(self):
        chart = build_charts(rows(0.0, 500))[0]
        self.assertEqual(chart['values'], [0.0, 500.0])
        self.assertEqual(chart['average'], 250.0)

    def test_values_are_rounded_for_the_chart(self):
        chart = build_charts(rows(1234.5678))[0]
        self.assertEqual(chart['values'], [1234.6])


if __name__ == '__main__':
    unittest.main()
