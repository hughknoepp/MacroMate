"""Run with:  python -m unittest discover -v   (from the project folder)"""
import unittest
from types import SimpleNamespace

from micronutrients import (MICRONUTRIENTS, extract_micronutrients, format_amount, group_rows,
                            micronutrient_totals, scale_micronutrients)


def entry(number, unit, amount, name='x'):
    return {'nutrient': {'number': str(number), 'name': name, 'unitName': unit}, 'amount': amount}


def record(*entries):
    return {'foodNutrients': list(entries)}


def item(**micronutrients):
    return SimpleNamespace(micronutrients=micronutrients or None)


class ExtractionTests(unittest.TestCase):
    def test_reads_each_nutrient_by_its_usda_number(self):
        found = extract_micronutrients(record(
            entry(269, 'g', 12.5), entry(301, 'mg', 120), entry(307, 'mg', 400), entry(303, 'mg', 2.5),
            entry(401, 'mg', 30), entry(323, 'mg', 1.1), entry(430, 'µg', 20), entry(404, 'mg', .2),
            entry(405, 'mg', .3), entry(406, 'mg', 4), entry(410, 'mg', .5), entry(415, 'mg', .6),
            entry(418, 'µg', 1.4), entry(320, 'µg', 90), entry(328, 'µg', 2), entry(435, 'µg', 80)))
        self.assertEqual(found, {
            'sugars_g': 12.5, 'calcium_mg': 120, 'sodium_mg': 400, 'iron_mg': 2.5, 'vitamin_c_mg': 30,
            'vitamin_e_mg': 1.1, 'vitamin_k_ug': 20, 'thiamin_mg': .2, 'riboflavin_mg': .3, 'niacin_mg': 4,
            'pantothenic_acid_mg': .5, 'vitamin_b6_mg': .6, 'vitamin_b12_ug': 1.4, 'vitamin_a_ug': 90,
            'vitamin_d_ug': 2, 'folate_ug': 80})

    def test_every_tracked_nutrient_can_be_found(self):
        every = record(*[entry(n, u, 1) for m in MICRONUTRIENTS for n, u, _ in m.sources])
        self.assertEqual(set(extract_micronutrients(every)), {m.key for m in MICRONUTRIENTS})

    def test_nutrients_the_record_lacks_are_left_out_not_zero(self):
        self.assertEqual(extract_micronutrients(record(entry(301, 'mg', 50))), {'calcium_mg': 50})
        self.assertEqual(extract_micronutrients({}), {})
        self.assertEqual(extract_micronutrients({'foodNutrients': None}), {})

    def test_a_reported_zero_is_kept(self):
        self.assertEqual(extract_micronutrients(record(entry(307, 'mg', 0))), {'sodium_mg': 0})

    def test_vitamin_d_converts_iu_exactly_and_prefers_micrograms(self):
        self.assertAlmostEqual(extract_micronutrients(record(entry(324, 'IU', 400)))['vitamin_d_ug'], 10)
        both = record(entry(324, 'IU', 400), entry(328, 'µg', 7))
        self.assertEqual(extract_micronutrients(both)['vitamin_d_ug'], 7)

    def test_vitamin_a_converts_iu_and_prefers_rae(self):
        self.assertAlmostEqual(extract_micronutrients(record(entry(318, 'IU', 1000)))['vitamin_a_ug'], 300)
        both = record(entry(318, 'IU', 1000), entry(320, 'µg', 150))
        self.assertEqual(extract_micronutrients(both)['vitamin_a_ug'], 150)

    def test_folate_prefers_dfe_then_total(self):
        self.assertEqual(extract_micronutrients(record(entry(417, 'µg', 60)))['folate_ug'], 60)
        self.assertEqual(extract_micronutrients(record(entry(417, 'µg', 60), entry(435, 'µg', 90)))['folate_ug'], 90)

    def test_greek_mu_and_micro_sign_are_the_same_unit(self):
        self.assertEqual(extract_micronutrients(record(entry(430, 'μg', 5))), {'vitamin_k_ug': 5})  # Greek mu
        self.assertEqual(extract_micronutrients(record(entry(430, 'µg', 5))), {'vitamin_k_ug': 5})  # micro sign

    def test_an_unexpected_unit_is_ignored_rather_than_misread(self):
        self.assertEqual(extract_micronutrients(record(entry(301, 'g', 1), entry(318, 'µg', 5))), {})

    def test_first_entry_wins_and_other_nutrients_are_ignored(self):
        found = extract_micronutrients(record(entry(301, 'mg', 10), entry(301, 'mg', 99), entry(999, 'mg', 5)))
        self.assertEqual(found, {'calcium_mg': 10})

    def test_malformed_entries_are_skipped_without_crashing(self):
        messy = record('junk', None, {'amount': 5}, {'nutrient': 'x', 'amount': 5}, entry(301, 'mg', None),
                       entry(301, 'mg', 'lots'), entry(301, 'mg', True), entry(301, 'mg', -4), entry(307, 'mg', 80))
        self.assertEqual(extract_micronutrients(messy), {'sodium_mg': 80})

    def test_numbers_may_arrive_as_integers(self):
        record_with_int = record({'nutrient': {'number': 301, 'unitName': 'mg'}, 'amount': 7})
        self.assertEqual(extract_micronutrients(record_with_int), {'calcium_mg': 7})


class ScalingAndTotalsTests(unittest.TestCase):
    def test_scaling_to_the_portion_eaten(self):
        self.assertEqual(scale_micronutrients({'calcium_mg': 120, 'iron_mg': 0.4}, 1.5), {'calcium_mg': 180, 'iron_mg': 0.6})
        self.assertEqual(scale_micronutrients({}, 2), {})

    def test_totals_add_up_across_items(self):
        rows = {r['key']: r for r in micronutrient_totals([item(calcium_mg=100, iron_mg=1), item(calcium_mg=50, iron_mg=2)])}
        self.assertEqual((rows['calcium_mg']['total'], rows['calcium_mg']['complete']), (150, True))
        self.assertEqual(rows['iron_mg']['total'], 3)

    def test_a_nutrient_nobody_reports_has_no_total(self):
        row = {r['key']: r for r in micronutrient_totals([item(calcium_mg=100)])}['sodium_mg']
        self.assertEqual((row['total'], row['complete']), (None, False))

    def test_partial_reporting_is_flagged_as_incomplete(self):
        rows = {r['key']: r for r in micronutrient_totals([item(calcium_mg=100), item(), item(sodium_mg=5)])}
        self.assertEqual((rows['calcium_mg']['total'], rows['calcium_mg']['complete']), (100, False))

    def test_items_logged_before_tracking_have_no_data(self):
        rows = micronutrient_totals([item(), item()])  # micronutrients = None on both
        self.assertTrue(all(r['total'] is None for r in rows))

    def test_a_reported_zero_counts_as_data(self):
        row = {r['key']: r for r in micronutrient_totals([item(sodium_mg=0)])}['sodium_mg']
        self.assertEqual((row['total'], row['complete']), (0, True))

    def test_rows_are_grouped_in_display_order(self):
        groups = group_rows(micronutrient_totals([]))
        self.assertEqual([g for g, _ in groups], ['Sugar & minerals', 'Vitamins'])
        self.assertEqual([r['label'] for r in groups[0][1]], ['Sugars', 'Calcium', 'Sodium', 'Iron'])

    def test_format_amount(self):
        self.assertEqual([format_amount(v) for v in (1234.5, 120, 12.34, 1, 0.456, 0)], ['1,234', '120', '12.3', '1.0', '0.46', '0.00'])


if __name__ == '__main__':
    unittest.main()
