"""Run with:  python -m unittest discover -v   (from the project folder)"""
import unittest
from datetime import date
from unittest.mock import patch

from flask import Flask
from sqlalchemy.exc import IntegrityError
from werkzeug.datastructures import MultiDict

from models import Profile, User, db, save_profile
from personal_details import metric_values, parse_form

GOOD = {'gender': 'female', 'age': '35', 'unit_system': 'metric', 'weight': '65', 'height': '1.68', 'activity_level': 'lightly_active'}


def form(**changes):
    data = {**GOOD, **changes}
    return MultiDict({k: v for k, v in data.items() if v is not None})


class ParseFormTests(unittest.TestCase):
    def test_valid_details_come_back_typed(self):
        values, error = parse_form(form())
        self.assertIsNone(error)
        self.assertEqual(values, {'gender': 'female', 'age': 35, 'unit_system': 'metric', 'weight': 65.0, 'height': 1.68, 'activity_level': 'lightly_active'})
        self.assertIsInstance(values['age'], int)

    def test_surrounding_spaces_are_ignored(self):
        self.assertEqual(parse_form(form(age='  40 ', weight=' 70.5'))[0]['weight'], 70.5)

    def test_every_field_is_required(self):
        for field in GOOD:
            self.assertEqual(parse_form(form(**{field: None})), (None, 'All fields are required.'), field)
            self.assertEqual(parse_form(form(**{field: '  '})), (None, 'All fields are required.'), field)

    def test_only_one_choice_per_group(self):
        crafted = MultiDict(GOOD); crafted.add('gender', 'male')
        self.assertEqual(parse_form(crafted), (None, 'Please select only one option for gender.'))
        crafted = MultiDict(GOOD); crafted.add('activity_level', 'sedentary')
        self.assertEqual(parse_form(crafted), (None, 'Please select only one option for activity level.'))

    def test_choices_must_be_from_the_list(self):
        self.assertEqual(parse_form(form(gender='other')), (None, 'Invalid selection for gender.'))
        self.assertEqual(parse_form(form(unit_system='stone')), (None, 'Invalid selection for unit system.'))
        self.assertEqual(parse_form(form(activity_level='extreme')), (None, 'Invalid selection for activity level.'))

    def test_numbers_must_be_numbers(self):
        message = 'Age must be a whole number, and weight and height must be numbers.'
        for changes in ({'age': 'abc'}, {'age': '1.5'}, {'weight': 'heavy'}, {'height': ''.join('x')}):
            self.assertEqual(parse_form(form(**changes)), (None, message), changes)

    def test_age_range(self):
        for age in ('0', '-3', '121'):
            self.assertEqual(parse_form(form(age=age)), (None, 'Age must be between 1 and 120.'), age)
        self.assertIsNone(parse_form(form(age='1'))[1])
        self.assertIsNone(parse_form(form(age='120'))[1])


class MetricValuesTests(unittest.TestCase):
    def test_metric_is_unchanged(self):
        self.assertEqual(metric_values('metric', 80, 1.8), (80, 1.8))

    def test_imperial_is_converted(self):
        kg, m = metric_values('imperial', 176, 70)
        self.assertAlmostEqual(kg, 79.832, places=3)      # 176 lb x 0.453592
        self.assertAlmostEqual(m, 1.778, places=3)        # 70 in x 0.0254


class SavedProfileTests(unittest.TestCase):
    """The database side, using a throwaway in-memory database."""

    def setUp(self):
        self.app = Flask('profile-tests')
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        db.init_app(self.app)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        for n in (1, 2):
            db.session.add(User(id=n, username=f'user{n}', email=f'u{n}@x.com', password_hash='x'))
        db.session.commit()
        self.values = parse_form(form())[0]

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()

    def test_saved_details_come_back_exactly_as_entered(self):
        save_profile(1, {**self.values, 'unit_system': 'imperial', 'weight': 176.5, 'height': 70.25})
        db.session.remove()
        row = Profile.query.filter_by(user_id=1).one()
        self.assertEqual((row.gender, row.age, row.unit_system, row.weight, row.height, row.activity_level),
                         ('female', 35, 'imperial', 176.5, 70.25, 'lightly_active'))
        self.assertEqual(row.updated_on, date.today())

    def test_saving_again_replaces_instead_of_adding(self):
        save_profile(1, self.values)
        save_profile(1, {**self.values, 'age': 36, 'weight': 63.0, 'activity_level': 'very_active'})
        rows = Profile.query.filter_by(user_id=1).all()
        self.assertEqual([(r.age, r.weight, r.activity_level) for r in rows], [(36, 63.0, 'very_active')])

    def test_each_user_has_their_own_details(self):
        save_profile(1, self.values)
        save_profile(2, {**self.values, 'gender': 'male', 'age': 50})
        self.assertEqual(Profile.query.filter_by(user_id=1).one().age, 35)
        self.assertEqual((Profile.query.filter_by(user_id=2).one().gender, Profile.query.count()), ('male', 2))

    def test_the_database_allows_only_one_profile_per_user(self):
        save_profile(1, self.values)
        db.session.add(Profile(user_id=1, gender='male', age=20, unit_system='metric', weight=70, height=1.8, activity_level='sedentary'))
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()
        self.assertEqual(Profile.query.count(), 1)

    def test_losing_a_race_updates_the_winners_row(self):
        save_profile(1, self.values)                       # the "other request" got there first
        real, lookups = Profile.query, []

        class MissesTheFirstLookup:                        # this request looked before the row existed
            def filter_by(self, **kwargs):
                query = real.filter_by(**kwargs)
                if lookups:
                    return query
                lookups.append(1)
                return type('Empty', (), {'first': lambda self: None, 'one': query.one})()

        with patch.object(Profile, 'query', MissesTheFirstLookup()):
            save_profile(1, {**self.values, 'age': 41})
        self.assertEqual([(r.user_id, r.age) for r in Profile.query.all()], [(1, 41)])


if __name__ == '__main__':
    unittest.main()
