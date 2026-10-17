"""Run with:  python -m unittest discover -v   (from the project folder)"""
import itertools
import unittest

from macros import CARB_MIN_GRAMS, carb_recommendations

# A 30-year-old man, 80 kg, sedentary: calorie ranges (midpoints 1,695 / 2,135 / 2,515) and protein ranges
RANGES = {'lose': {'low': 1500, 'high': 1890}, 'maintain': {'low': 2030, 'high': 2240}, 'gain': {'low': 2390, 'high': 2640}}
PROTEIN = [{'key': 'lose', 'grams_low': 95, 'grams_high': 130},       # midpoint 112.5 g = 450 kcal
           {'key': 'maintain', 'grams_low': 65, 'grams_high': 80},     # midpoint 72.5 g = 290 kcal
           {'key': 'gain', 'grams_low': 80, 'grams_high': 110}]        # midpoint 95 g = 380 kcal


def carbs(age=30, ranges=RANGES, protein=PROTEIN, notes=()):
    return carb_recommendations(age, ranges, protein, notes)


def goal(rec, key):
    return next((g for g in rec['goals'] if g['key'] == key), None)


class CarbTests(unittest.TestCase):
    def test_what_is_left_after_protein_and_fat_matches_hand_calculation(self):
        rec = carbs()
        # maintain: (2135 - 290 - 35% fat)/4 = 274 g up to the 65% cap of 347 g; lose: 163-227 g; gain: 314 g up to the 65% cap of 409 g
        self.assertEqual([(g['key'], g['grams_low'], g['grams_high']) for g in rec['goals']],
                         [('lose', 165, 225), ('maintain', 275, 345), ('gain', 315, 410)])

    def test_share_of_calories(self):
        self.assertEqual([(g['percent_low'], g['percent_high']) for g in carbs()['goals']], [(39, 53), (52, 65), (50, 65)])

    def test_fiber_is_14_g_per_1000_calories_and_added_sugar_stays_under_10_percent(self):
        goals = {g['key']: g for g in carbs()['goals']}
        self.assertEqual([goals[k]['fiber_g'] for k in ('lose', 'maintain', 'gain')], [25, 30, 35])     # 23.7, 29.9, 35.2
        self.assertEqual([goals[k]['added_sugar_max_g'] for k in ('lose', 'maintain', 'gain')], [40, 50, 60])  # 42.4, 53.4, 62.9

    def test_never_planned_above_65_percent_of_calories(self):
        rec = carbs(ranges={**RANGES, 'maintain': {'low': 2900, 'high': 3100}},
                    protein=[{'key': 'maintain', 'grams_low': 60, 'grams_high': 60}])   # leaves 540 g, but 65% of 3,000 is 487 g
        self.assertEqual(goal(rec, 'maintain')['grams_high'], 490)
        self.assertEqual(goal(rec, 'maintain')['percent_high'], 65)

    def test_never_below_the_130_g_minimum(self):
        rec = carbs(ranges={'maintain': {'low': 1150, 'high': 1250}}, protein=[{'key': 'maintain', 'grams_low': 90, 'grams_high': 110}])
        g = goal(rec, 'maintain')                       # 1,200 kcal: 95-140 g left over, raised to 130-140 g
        self.assertEqual((g['grams_low'], g['grams_high'], g['at_minimum']), (130, 140, False))

    def test_a_heavy_protein_target_cannot_push_carbs_below_the_minimum(self):
        rec = carbs(ranges={'maintain': {'low': 1150, 'high': 1250}}, protein=[{'key': 'maintain', 'grams_low': 180, 'grams_high': 200}])
        g = goal(rec, 'maintain')                       # only 50 g would be left, so it is held at 130 g
        self.assertEqual((g['grams_low'], g['grams_high'], g['at_minimum']), (130, 130, True))

    def test_the_three_macros_roughly_add_up_to_the_calorie_target(self):
        g = goal(carbs(), 'lose')                       # 225 g carbs + 112.5 g protein + 20% fat vs 1,695 kcal
        self.assertAlmostEqual(g['grams_high'] * 4 + 112.5 * 4 + 0.20 * 1695, 1695, delta=25)

    def test_goals_without_calories_or_protein_are_left_out(self):
        self.assertEqual([g['key'] for g in carbs(ranges={**RANGES, 'lose': None})['goals']], ['maintain', 'gain'])
        self.assertEqual([g['key'] for g in carbs(protein=PROTEIN[1:])['goals']], ['maintain', 'gain'])

    def test_under_18_gets_no_targets_and_notes_pass_through(self):
        rec = carbs(age=17, notes=['a note'])
        self.assertEqual((rec['minor'], rec['goals'], rec['notes']), (True, [], ['a note']))
        self.assertEqual(carbs(age=18, notes=['n'])['notes'], ['n'])

    def test_every_target_is_sensible_across_many_people(self):
        for mid, protein_g, in itertools.product(range(1300, 4200, 150), (50, 80, 120, 180)):
            rec = carbs(ranges={'maintain': {'low': mid - 100, 'high': mid + 100}},
                        protein=[{'key': 'maintain', 'grams_low': protein_g - 10, 'grams_high': protein_g + 10}])
            g = goal(rec, 'maintain')
            self.assertLessEqual(g['grams_low'], g['grams_high'], (mid, protein_g))
            self.assertGreaterEqual(g['grams_low'], CARB_MIN_GRAMS)
            self.assertLessEqual(g['percent_high'], 66, (mid, protein_g))   # 65%, allowing for rounding to 5 g
            self.assertEqual((g['grams_low'] % 5, g['grams_high'] % 5), (0, 0))


if __name__ == '__main__':
    unittest.main()
