"""Daily protein recommendations from a person's body measurements, activity and goal.

The ranges are general guidance for healthy adults, drawn from commonly cited sources: the
US/Canadian RDA (0.8 g per kg of body weight), sports-nutrition position statements from the
ACSM and ISSN (about 1.2-2.0 g/kg for active people), research on gaining muscle (about
1.6-2.2 g/kg), and guidance for older adults (at least 1.0-1.2 g/kg). They are estimates,
not medical advice.
"""
import math

KG_PER_LB = 0.453592
KCAL_PER_G_PROTEIN = 4
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

GOAL_TITLES = {'lose': 'Lose weight', 'maintain': 'Maintain weight', 'gain': 'Gain weight'}
GOAL_ORDER = ('lose', 'maintain', 'gain')


def _round_to_5(value):
    """Nearest 5 (halves round up), so the numbers don't look more exact than they are."""
    return int(math.floor(value / 5 + 0.5) * 5)


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
