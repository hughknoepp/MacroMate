"""Sugars, minerals and vitamins: what we track, how to read them from a USDA food record,
and how to total them for the summary page.

Records are matched on USDA's nutrient *number* (e.g. 301 = calcium), which stays the same
across food types, unlike nutrient names. Many foods report only some of these (packaged
foods often list just sugars, calcium, sodium, iron and vitamins A, C and D), so a nutrient
the USDA doesn't report is left out, never recorded as zero.
"""
from collections import namedtuple

# sources: in order of preference, (USDA nutrient number, unit USDA reports, factor to our unit)
Micronutrient = namedtuple('Micronutrient', 'key label unit group sources')

SUGAR_AND_MINERALS = 'Sugar & minerals'
VITAMINS = 'Vitamins'

MICRONUTRIENTS = (
    Micronutrient('sugars_g', 'Sugars', 'g', SUGAR_AND_MINERALS, (('269', 'g', 1),)),
    Micronutrient('calcium_mg', 'Calcium', 'mg', SUGAR_AND_MINERALS, (('301', 'mg', 1),)),
    Micronutrient('sodium_mg', 'Sodium', 'mg', SUGAR_AND_MINERALS, (('307', 'mg', 1),)),
    Micronutrient('iron_mg', 'Iron', 'mg', SUGAR_AND_MINERALS, (('303', 'mg', 1),)),
    # Vitamin A: RAE directly, else IU (1 IU = 0.3 ug RAE, the usual label conversion)
    Micronutrient('vitamin_a_ug', 'Vitamin A', 'µg RAE', VITAMINS, (('320', 'µg', 1), ('318', 'iu', 0.3))),
    Micronutrient('vitamin_c_mg', 'Vitamin C', 'mg', VITAMINS, (('401', 'mg', 1),)),
    # Vitamin D: micrograms directly, else IU (exactly 40 IU per ug)
    Micronutrient('vitamin_d_ug', 'Vitamin D', 'µg', VITAMINS, (('328', 'µg', 1), ('324', 'iu', 1 / 40))),
    Micronutrient('vitamin_e_mg', 'Vitamin E', 'mg', VITAMINS, (('323', 'mg', 1),)),
    Micronutrient('vitamin_k_ug', 'Vitamin K', 'µg', VITAMINS, (('430', 'µg', 1),)),
    Micronutrient('thiamin_mg', 'Thiamin (B1)', 'mg', VITAMINS, (('404', 'mg', 1),)),
    Micronutrient('riboflavin_mg', 'Riboflavin (B2)', 'mg', VITAMINS, (('405', 'mg', 1),)),
    Micronutrient('niacin_mg', 'Niacin (B3)', 'mg', VITAMINS, (('406', 'mg', 1),)),
    Micronutrient('pantothenic_acid_mg', 'Pantothenic acid (B5)', 'mg', VITAMINS, (('410', 'mg', 1),)),
    Micronutrient('vitamin_b6_mg', 'Vitamin B6', 'mg', VITAMINS, (('415', 'mg', 1),)),
    # Folate: dietary folate equivalents if given, else total folate
    Micronutrient('folate_ug', 'Folate (B9)', 'µg', VITAMINS, (('435', 'µg', 1), ('417', 'µg', 1))),
    Micronutrient('vitamin_b12_ug', 'Vitamin B12', 'µg', VITAMINS, (('418', 'µg', 1),)),
)


def _unit(name):
    """Lower-case a unit and treat the Greek mu and the micro sign as the same character."""
    return (name or '').strip().lower().replace('μ', 'µ')


def extract_micronutrients(food_detail):
    """Per-100 g amounts of the tracked micronutrients found in a USDA food record.

    Returns {key: amount} for the ones the record reports, in our units. Anything missing,
    non-numeric, negative, or reported in an unexpected unit is left out. If a nutrient is
    listed twice, the first entry wins.
    """
    reported = {}
    for entry in food_detail.get('foodNutrients') or []:
        if not isinstance(entry, dict):
            continue
        nutrient = entry.get('nutrient')
        amount = entry.get('amount')
        if (not isinstance(nutrient, dict) or isinstance(amount, bool)
                or not isinstance(amount, (int, float)) or amount < 0):
            continue
        reported.setdefault((str(nutrient.get('number')), _unit(nutrient.get('unitName'))), amount)

    found = {}
    for nutrient in MICRONUTRIENTS:
        for number, unit, factor in nutrient.sources:
            amount = reported.get((number, _unit(unit)))
            if amount is not None:
                found[nutrient.key] = amount * factor
                break
    return found


def scale_micronutrients(per_100g, scale):
    """Per-100 g amounts -> amounts for the portion eaten (scale = grams / 100)."""
    return {key: round(amount * scale, 4) for key, amount in per_100g.items()}


def micronutrient_totals(items):
    """One row per tracked micronutrient, totalled over a day's logged items.

    `total` is None if no item reports that nutrient. `complete` is False if some items
    report it and others don't, meaning the total may be low. Items logged before this
    tracking existed have no micronutrient data.
    """
    rows = []
    for nutrient in MICRONUTRIENTS:
        reported = [item.micronutrients[nutrient.key] for item in items
                    if item.micronutrients and nutrient.key in item.micronutrients]
        rows.append({
            'key': nutrient.key, 'label': nutrient.label, 'unit': nutrient.unit, 'group': nutrient.group,
            'total': sum(reported) if reported else None,
            'complete': len(reported) == len(items),
        })
    return rows


def group_rows(rows):
    """Split totals into [(group name, [rows])] keeping the display order."""
    groups = {}
    for row in rows:
        groups.setdefault(row['group'], []).append(row)
    return list(groups.items())


def format_amount(value):
    """Readable amount: 1,234 / 12.3 / 0.45."""
    if value >= 100:
        return f'{value:,.0f}'
    if value >= 1:
        return f'{value:.1f}'
    return f'{value:.2f}'
