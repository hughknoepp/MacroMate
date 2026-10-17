"""Daily protein, carbohydrate and fat recommendations, built to fit together.

Each goal (lose, maintain, gain) has a calorie range from nutrition.calorie_suggestions. Protein,
carbs and fat for that goal are all worked out against the middle of that range:

* Protein comes first: grams per kg of body weight by activity level and goal. The ranges are
  general guidance for healthy adults drawn from commonly cited sources: the US/Canadian RDA
  (0.8 g per kg), sports-nutrition position statements from the ACSM and ISSN (about 1.2-2.0 g/kg
  for active people), research on gaining muscle (about 1.6-2.2 g/kg), and guidance for older
  adults (at least 1.0-1.2 g/kg).
* Fat is 20-35% of calories (the US/Canadian acceptable range for adults), with saturated fat
  under 10% of calories.
* Carbs are what is left once protein and fat are accounted for, so the three fit together.
  Carbs are never planned above 65% of calories (top of the usual 45-65% range) or below 130 g
  a day (the official daily minimum for adults).
* Fiber is about 14 g per 1,000 calories, and added sugars stay under 10% of calories.

Estimates for healthy adults, not medical advice.
"""
import math

KG_PER_LB = 0.453592
KCAL_PER_G_PROTEIN = 4
KCAL_PER_G_CARB = 4
KCAL_PER_G_FAT = 9

GOAL_TITLES = {'lose': 'Lose weight', 'maintain': 'Maintain weight', 'gain': 'Gain weight'}
GOAL_ORDER = ('lose', 'maintain', 'gain')

# --- Protein ---
MAX_PROTEIN_SHARE = 0.35         # top of the recommended 10-35% of calories from protein
EXCESS_WEIGHT_COUNTED = 0.25     # share of weight above a BMI of 25 used when BMI is 30+
MEAL_G_PER_KG = (0.25, 0.4)      # protein per meal that supports muscle maintenance and growth

# g of protein per kg of body weight per day, by activity level: (low, high)
GRAMS_PER_KG = {
    'maintain': {'sedentary': (0.8, 1.0), 'lightly_active': (1.0, 1.2),
                 'moderately_active': (1.2, 1.6), 'very_active': (1.4, 2.0)},
    'lose':     {'sedentary': (1.2, 1.6), 'lightly_active': (1.2, 1.6),   # higher while eating
                 'moderately_active': (1.6, 2.0), 'very_active': (1.6, 2.2)},  # less, to keep muscle
    'gain':     {'sedentary': (1.0, 1.4), 'lightly_active': (1.2, 1.6),
                 'moderately_active': (1.6, 2.0), 'very_active': (1.6, 2.2)},
}
OLDER_ADULT_AGE = 65
OLDER_ADULT_MINIMUM = {'maintain': 1.0, 'lose': 1.2, 'gain': 1.2}   # g/kg

# --- Carbs and fat ---
FAT_SHARE = (0.20, 0.35)           # of calories
SATURATED_FAT_MAX_SHARE = 0.10     # of calories
CARB_MAX_SHARE = 0.65              # of calories
CARB_MIN_GRAMS = 130               # per day
FIBER_G_PER_1000_KCAL = 14
ADDED_SUGAR_MAX_SHARE = 0.10       # of calories


# --- Helpers shared by all three ---
def _round_to_5(value):
    """Nearest 5 (halves round up), so the numbers don't look more exact than they are."""
    return int(math.floor(value / 5 + 0.5) * 5)


def _midpoint(calories):
    return (calories['low'] + calories['high']) / 2


def _round_down(value, step):
    return int(math.floor(value / step) * step)


def _minor_result(notes):
    return {'minor': True, 'goals': [], 'notes': list(notes)}


# --- Protein ---
def basis_weight_kg(weight_kg, height_m, bmi):
    """The weight protein targets are based on, and whether it was adjusted.

    At a BMI of 30 or more, body fat would inflate a per-kg target, so it uses the weight at
    a BMI of 25 plus a quarter of the excess. Otherwise it is simply your weight.
    """
    if bmi >= 30:
        reference = 25 * height_m ** 2
        return reference + EXCESS_WEIGHT_COUNTED * (weight_kg - reference), True
    return weight_kg, False


def protein_recommendations(weight_kg, height_m, age, activity_level, bmi, calorie_ranges, calorie_notes=()):
    """Protein targets for each goal that the calorie suggestions offer.

    `calorie_ranges` is {'lose': {...} or None, 'maintain': {...}, 'gain': {...} or None},
    each with 'low'/'high' calories, as produced by nutrition.calorie_suggestions. A goal with
    no calorie range (for example, losing weight when underweight) gets no protein target.
    Returns {'minor', 'basis_kg', 'adjusted', 'goals': [...], 'per_meal': (low, high), 'notes': [...]}.
    """
    notes = list(calorie_notes)
    if age < 18:
        return {'minor': True, 'basis_kg': None, 'adjusted': False, 'goals': [], 'per_meal': None, 'notes': notes}

    basis, adjusted = basis_weight_kg(weight_kg, height_m, bmi)
    goals = []
    for goal in GOAL_ORDER:
        calories = calorie_ranges.get(goal)
        if calories is None:
            continue
        per_kg_low, per_kg_high = GRAMS_PER_KG[goal][activity_level]
        if age >= OLDER_ADULT_AGE:
            per_kg_low = max(per_kg_low, OLDER_ADULT_MINIMUM[goal])
            per_kg_high = max(per_kg_high, per_kg_low)

        grams_low, grams_high = _round_to_5(per_kg_low * basis), _round_to_5(per_kg_high * basis)
        mid_calories = (calories['low'] + calories['high']) / 2
        cap = int(MAX_PROTEIN_SHARE * mid_calories / KCAL_PER_G_PROTEIN // 5 * 5)
        capped = grams_high > cap
        if capped:
            grams_high = cap
            grams_low = min(grams_low, grams_high)
            per_kg_low, per_kg_high = min(per_kg_low, grams_high / basis), grams_high / basis

        goals.append({
            'key': goal, 'title': GOAL_TITLES[goal],
            'grams_low': grams_low, 'grams_high': grams_high,
            'per_kg_low': round(per_kg_low, 1), 'per_kg_high': round(per_kg_high, 1),
            'percent_low': round(grams_low * KCAL_PER_G_PROTEIN / mid_calories * 100),
            'percent_high': round(grams_high * KCAL_PER_G_PROTEIN / mid_calories * 100),
            'capped': capped,
        })

    per_meal = tuple(_round_to_5(share * basis) for share in MEAL_G_PER_KG)
    return {'minor': False, 'basis_kg': basis, 'adjusted': adjusted, 'goals': goals,
            'per_meal': per_meal, 'notes': notes}


# --- Carbs ---
def carb_recommendations(age, calorie_ranges, protein_goals, calorie_notes=()):
    """Carb targets for each goal the calorie suggestions offer.

    `calorie_ranges` is {'lose': {...} or None, 'maintain': {...}, 'gain': {...} or None} (each with
    'low'/'high' calories). `protein_goals` is the 'goals' list from protein_recommendations;
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


# --- Fat ---
def fat_recommendations(age, calorie_ranges, calorie_notes=()):
    """Fat targets for each goal the calorie suggestions offer: 20-35% of calories, with the
    most saturated fat that stays under 10%. Returns {'minor', 'goals': [...], 'notes': [...]}."""
    notes = list(calorie_notes)
    if age < 18:
        return _minor_result(notes)

    goals = []
    for key in GOAL_ORDER:
        calories = calorie_ranges.get(key)
        if calories is None:
            continue
        mid = _midpoint(calories)
        goals.append({
            'key': key, 'title': GOAL_TITLES[key],
            'grams_low': _round_to_5(FAT_SHARE[0] * mid / KCAL_PER_G_FAT),
            'grams_high': _round_to_5(FAT_SHARE[1] * mid / KCAL_PER_G_FAT),
            'percent_low': round(FAT_SHARE[0] * 100), 'percent_high': round(FAT_SHARE[1] * 100),
            'saturated_max_g': _round_down(SATURATED_FAT_MAX_SHARE * mid / KCAL_PER_G_FAT, 1),
        })
    return {'minor': False, 'goals': goals, 'notes': notes}
