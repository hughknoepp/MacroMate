"""Run with:  python -m unittest discover -v   (from the project folder)"""
import itertools
import unittest

from protein import GRAMS_PER_KG, _round_to_5, basis_weight_kg, protein_recommendations

# Calorie ranges as produced for a 30-year-old man, 80 kg, 1.8 m, sedentary (TDEE 2,136)
RANGES = {'lose': {'low': 1500, 'high': 1890}, 'maintain': {'low': 2030, 'high': 2240}, 'gain': {'low': 2390, 'high': 2640}}


def recommend(weight=80, height=1.8, age=30, activity='sedentary', bmi=24.69, ranges=RANGES, notes=()):
    return protein_recommendations(weight, height, age, activity, bmi, ranges, notes)


def goal(rec, key):
    return next((g for g in rec['goals'] if g['key'] == key), None)


class TargetTests(unittest.TestCase):
    def test_sedentary_adult_matches_hand_calculation(self):
        rec = recommend()
        # lose 1.2-1.6 g/kg x 80 = 96-128 -> 95-130 | maintain 0.8-1.0 -> 64-80 -> 65-80 | gain 1.0-1.4 -> 80-112 -> 80-110
        self.assertEqual([(g['key'], g['grams_low'], g['grams_high']) for g in rec['goals']],
                         [('lose', 95, 130), ('maintain', 65, 80), ('gain', 80, 110)])
        self.assertEqual((rec['basis_kg'], rec['adjusted'], rec['minor']), (80, False, False))

    def test_percent_of_calories_uses_the_middle_of_the_calorie_range(self):
        maintain = goal(recommend(), 'maintain')   # midpoint 2,135 kcal; 65 g = 260 kcal, 80 g = 320 kcal
        self.assertEqual((maintain['percent_low'], maintain['percent_high']), (12, 15))

    def test_more_activity_means_more_protein(self):
        highs = [goal(recommend(activity=a), 'maintain')['grams_high'] for a in
                 ('sedentary', 'lightly_active', 'moderately_active', 'very_active')]
        self.assertEqual(highs, [80, 95, 130, 160])          # 1.0, 1.2, 1.6, 2.0 g/kg x 80, to the nearest 5
        self.assertEqual(highs, sorted(highs))

    def test_losing_weight_asks_for_at_least_as_much_as_maintaining(self):
        for activity in GRAMS_PER_KG['maintain']:
            rec = recommend(activity=activity)
            self.assertGreaterEqual(goal(rec, 'lose')['per_kg_low'], goal(rec, 'maintain')['per_kg_low'], activity)

    def test_older_adults_get_a_higher_floor(self):
        young, old = goal(recommend(age=30), 'maintain'), goal(recommend(age=70), 'maintain')
        self.assertEqual((young['per_kg_low'], old['per_kg_low']), (0.8, 1.0))
        self.assertEqual((goal(recommend(age=70), 'lose')['per_kg_low'], goal(recommend(age=70), 'gain')['per_kg_low']), (1.2, 1.2))
        self.assertEqual(goal(recommend(age=64), 'maintain')['per_kg_low'], 0.8)   # the floor starts at 65

    def test_a_goal_without_calorie_range_gets_no_protein_target(self):
        rec = recommend(ranges={**RANGES, 'lose': None})
        self.assertEqual([g['key'] for g in rec['goals']], ['maintain', 'gain'])
        self.assertEqual([g['key'] for g in recommend(ranges={'lose': None, 'maintain': RANGES['maintain'], 'gain': None})['goals']], ['maintain'])

    def test_calorie_notes_are_passed_through(self):
        self.assertEqual(recommend(notes=['a note'])['notes'], ['a note'])

    def test_under_18_gets_no_targets(self):
        rec = recommend(age=17)
        self.assertEqual((rec['minor'], rec['goals'], rec['per_meal']), (True, [], None))
        self.assertFalse(recommend(age=18)['minor'])


class WeightBasisTests(unittest.TestCase):
    def test_normal_weight_uses_actual_weight(self):
        self.assertEqual(basis_weight_kg(80, 1.8, 24.69), (80, False))
        self.assertEqual(basis_weight_kg(97, 1.8, 29.9), (97, False))

    def test_bmi_30_plus_uses_adjusted_weight(self):
        basis, adjusted = basis_weight_kg(120, 1.8, 37.04)    # reference 25 x 1.8^2 = 81; 81 + 0.25 x 39 = 90.75
        self.assertAlmostEqual(basis, 90.75)
        self.assertTrue(adjusted)
        rec = recommend(weight=120, bmi=37.04, activity='moderately_active')
        self.assertEqual(rec['basis_kg'], basis)
        self.assertEqual(goal(rec, 'maintain')['grams_low'], 110)      # 1.2 x 90.75 = 108.9 -> 110 (not 1.2 x 120 = 144)

    def test_adjusted_weight_is_between_reference_and_actual(self):
        basis, _ = basis_weight_kg(150, 1.7, 51.9)
        self.assertTrue(25 * 1.7 ** 2 < basis < 150)


class CapTests(unittest.TestCase):
    def test_target_is_held_to_35_percent_of_calories(self):
        # very active 90 kg, losing: 1.6-2.2 g/kg = 145-200 g, but 35% of 1,695 kcal is 148 g -> held at 145 g
        rec = recommend(weight=90, activity='very_active')
        lose = goal(rec, 'lose')
        self.assertTrue(lose['capped'])
        self.assertEqual((lose['grams_low'], lose['grams_high']), (145, 145))
        self.assertLessEqual(lose['percent_high'], 35)
        self.assertFalse(goal(rec, 'maintain')['capped'])

    def test_capped_per_kg_figure_matches_the_grams_shown(self):
        lose = goal(recommend(weight=90, activity='very_active'), 'lose')
        self.assertAlmostEqual(lose['per_kg_high'], 1.6, places=1)       # 145 g / 90 kg

    def test_no_target_ever_exceeds_the_cap_or_has_low_above_high(self):
        for activity, weight, age in itertools.product(GRAMS_PER_KG['lose'], (45, 60, 80, 100, 140), (20, 40, 70)):
            for g in recommend(weight=weight, age=age, activity=activity)['goals']:
                self.assertLessEqual(g['grams_low'], g['grams_high'])
                self.assertLessEqual(g['percent_high'], 35, (activity, weight, age, g['key']))
                self.assertEqual((g['grams_low'] % 5, g['grams_high'] % 5), (0, 0))


class HelperTests(unittest.TestCase):
    def test_rounding_to_5_rounds_halves_up(self):
        self.assertEqual([_round_to_5(v) for v in (62.4, 62.5, 62.6, 0, 2.4, 2.5, 100)], [60, 65, 65, 0, 0, 5, 100])

    def test_protein_per_meal(self):
        self.assertEqual(recommend()['per_meal'], (20, 30))      # 0.25 and 0.4 g/kg x 80 = 20 and 32 -> 20, 30


if __name__ == '__main__':
    unittest.main()
