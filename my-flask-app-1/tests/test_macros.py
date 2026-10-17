"""Run with:  python -m unittest discover -v   (from the project folder)"""
import itertools
import unittest

from macros import (CARB_MIN_GRAMS, GRAMS_PER_KG, _round_to_5, basis_weight_kg, carb_recommendations,
                    fat_recommendations, protein_recommendations)

# A 30-year-old man, 80 kg, sedentary: calorie ranges (midpoints 1,695 / 2,135 / 2,515) and protein ranges
RANGES = {'lose': {'low': 1500, 'high': 1890}, 'maintain': {'low': 2030, 'high': 2240}, 'gain': {'low': 2390, 'high': 2640}}
PROTEIN = [{'key': 'lose', 'grams_low': 95, 'grams_high': 130},       # midpoint 112.5 g = 450 kcal
           {'key': 'maintain', 'grams_low': 65, 'grams_high': 80},     # midpoint 72.5 g = 290 kcal
           {'key': 'gain', 'grams_low': 80, 'grams_high': 110}]        # midpoint 95 g = 380 kcal


def carbs(age=30, ranges=RANGES, protein=PROTEIN, notes=()):
    return carb_recommendations(age, ranges, protein, notes)


def fats(age=30, ranges=RANGES, notes=()):
    return fat_recommendations(age, ranges, notes)


def recommend(weight=80, height=1.8, age=30, activity='sedentary', bmi=24.69, ranges=RANGES, notes=()):
    return protein_recommendations(weight, height, age, activity, bmi, ranges, notes)


def goal(rec, key):
    return next((g for g in rec['goals'] if g['key'] == key), None)


class ProteinTargetTests(unittest.TestCase):
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


class ProteinWeightBasisTests(unittest.TestCase):
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


class ProteinCapTests(unittest.TestCase):
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


class ProteinHelperTests(unittest.TestCase):
    def test_rounding_to_5_rounds_halves_up(self):
        self.assertEqual([_round_to_5(v) for v in (62.4, 62.5, 62.6, 0, 2.4, 2.5, 100)], [60, 65, 65, 0, 0, 5, 100])

    def test_protein_per_meal(self):
        self.assertEqual(recommend()['per_meal'], (20, 30))      # 0.25 and 0.4 g/kg x 80 = 20 and 32 -> 20, 30


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


class FatTests(unittest.TestCase):
    def test_20_to_35_percent_of_calories_matches_hand_calculation(self):
        # maintain: 20% of 2,135 = 427 kcal = 47 g -> 45; 35% = 747 kcal = 83 g -> 85 (lose: 40-65, gain: 55-100)
        self.assertEqual([(g['key'], g['grams_low'], g['grams_high']) for g in fats()['goals']],
                         [('lose', 40, 65), ('maintain', 45, 85), ('gain', 55, 100)])

    def test_the_share_shown_is_the_rule_not_a_rounded_result(self):
        self.assertTrue(all((g['percent_low'], g['percent_high']) == (20, 35) for g in fats()['goals']))

    def test_saturated_fat_limit_is_just_under_10_percent(self):
        # 10% of 1,695 / 2,135 / 2,515 kcal = 18.8 / 23.7 / 27.9 g, rounded down so it stays under 10%
        self.assertEqual([g['saturated_max_g'] for g in fats()['goals']], [18, 23, 27])
        for g in fats()['goals']:
            self.assertLess(g['saturated_max_g'] * 9 / (({'lose': 1695, 'maintain': 2135, 'gain': 2515})[g['key']]), 0.10)

    def test_goals_without_calories_are_left_out(self):
        self.assertEqual([g['key'] for g in fats(ranges={'lose': None, 'maintain': RANGES['maintain'], 'gain': None})['goals']], ['maintain'])

    def test_under_18_gets_no_targets(self):
        rec = fats(age=17, notes=['a note'])
        self.assertEqual((rec['minor'], rec['goals'], rec['notes']), (True, [], ['a note']))

    def test_more_calories_means_more_fat(self):
        lows = [fats(ranges={'maintain': {'low': m - 100, 'high': m + 100}})['goals'][0]['grams_low'] for m in range(1400, 4000, 200)]
        self.assertEqual(lows, sorted(lows))


if __name__ == '__main__':
    unittest.main()
