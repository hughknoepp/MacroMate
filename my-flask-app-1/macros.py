"""Daily carbohydrate recommendations, built to fit together with the protein targets.

Each goal (lose, maintain, gain) has a calorie range from nutrition.calorie_suggestions. Protein,
carbs and fat for that goal are worked out against the middle of that range:

* Fat takes 20-35% of calories (the US/Canadian acceptable range for adults).
* Carbs are what is left once protein and fat are accounted for, so the three fit together.
  Carbs are never planned above 65% of calories (top of the usual 45-65% range) or below 130 g
  a day (the official daily minimum for adults).
* Fiber is about 14 g per 1,000 calories, and added sugars stay under 10% of calories.

General guidance for healthy adults, not medical advice.
"""
import math

from protein import GOAL_ORDER, GOAL_TITLES, KCAL_PER_G_PROTEIN, _round_to_5

KCAL_PER_G_CARB = 4

FAT_SHARE = (0.20, 0.35)           # of calories
CARB_MAX_SHARE = 0.65              # of calories
CARB_MIN_GRAMS = 130               # per day
FIBER_G_PER_1000_KCAL = 14
ADDED_SUGAR_MAX_SHARE = 0.10       # of calories


def _midpoint(calories):
    return (calories['low'] + calories['high']) / 2


def _round_down(value, step):
    return int(math.floor(value / step) * step)


def _minor_result(notes):
    return {'minor': True, 'goals': [], 'notes': list(notes)}


def carb_recommendations(age, calorie_ranges, protein_goals, calorie_notes=()):
    """Carb targets for each goal the calorie suggestions offer.

    `calorie_ranges` is {'lose': {...} or None, 'maintain': {...}, 'gain': {...} or None} (each with
    'low'/'high' calories). `protein_goals` is the 'goals' list from protein.protein_recommendations;
    the middle of each protein range is set aside before the rest is split between carbs and fat.
    Returns {'minor', 'goals': [...], 'notes': [...]}.
    """
    notes = list(calorie_notes)
    if age < 18:
        return _minor_result(notes)

    protein_by_goal = {g['key']: g for g in protein_goals}
    goals = []
    for key in GOAL_ORDER:
        calories = calorie_ranges.get(key)
        protein = protein_by_goal.get(key)
        if calories is None or protein is None:
            continue
        mid = _midpoint(calories)
        protein_kcal = (protein['grams_low'] + protein['grams_high']) / 2 * KCAL_PER_G_PROTEIN

        # What is left after protein, if fat takes its highest share (fewest carbs) or its lowest (most)
        fewest = (mid - protein_kcal - FAT_SHARE[1] * mid) / KCAL_PER_G_CARB
        most = min((mid - protein_kcal - FAT_SHARE[0] * mid) / KCAL_PER_G_CARB,
                   CARB_MAX_SHARE * mid / KCAL_PER_G_CARB)
        at_minimum = most < CARB_MIN_GRAMS
        high = max(most, CARB_MIN_GRAMS)
        low = min(max(fewest, CARB_MIN_GRAMS), high)

        grams_low, grams_high = _round_to_5(low), _round_to_5(high)
        goals.append({
            'key': key, 'title': GOAL_TITLES[key],
            'grams_low': grams_low, 'grams_high': grams_high,
            'percent_low': round(grams_low * KCAL_PER_G_CARB / mid * 100),
            'percent_high': round(grams_high * KCAL_PER_G_CARB / mid * 100),
            'fiber_g': _round_to_5(FIBER_G_PER_1000_KCAL * mid / 1000),
            'added_sugar_max_g': _round_down(ADDED_SUGAR_MAX_SHARE * mid / KCAL_PER_G_CARB, 5),
            'at_minimum': at_minimum,
        })
    return {'minor': False, 'goals': goals, 'notes': notes}
