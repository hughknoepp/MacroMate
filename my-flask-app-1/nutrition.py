from datetime import timedelta, date as date_type
from sqlalchemy import func
from models import db, MealLog, MealItem

def get_daily_items(user_id, log_date):
    """All food items a user logged on a date, oldest first, in a single query."""
    return (MealItem.query.join(MealLog)
            .filter(MealLog.user_id == user_id, MealLog.date == log_date)
            .order_by(MealItem.id)
            .all())

def totals_from_items(items):
    """Sum calories/protein/fat/carbs across a list of logged food items."""
    totals = {'calories': 0, 'protein_g': 0, 'carbs_g': 0, 'fat_g': 0}
    for item in items:
        totals['calories'] += item.calories or 0
        totals['protein_g'] += item.protein_g or 0
        totals['carbs_g'] += item.carbs_g or 0
        totals['fat_g'] += item.fat_g or 0
    return totals

def get_daily_totals(user_id, log_date = None):
    """Sum calories/protein/fat/carbs across all foods logged by a user on a given date"""
    log_date = log_date or date_type.today()
    return totals_from_items(get_daily_items(user_id, log_date))

def get_rolling_average(user_id, days=7):
    """Calculate the rolling average of calories/protein/fat/carbs over the last `days` days.

    Days with nothing logged count as zero, so this is the total over the window divided by
    `days`. The database adds everything up in one query; there is no need to fetch each day.
    """
    assert days > 0 and isinstance(days, int) # Ensure days is a positive integer

    today = date_type.today()
    start_date = today - timedelta(days=days - 1)
    calories, protein_g, carbs_g, fat_g = (
        db.session.query(
            func.coalesce(func.sum(MealItem.calories), 0),
            func.coalesce(func.sum(MealItem.protein_g), 0),
            func.coalesce(func.sum(MealItem.carbs_g), 0),
            func.coalesce(func.sum(MealItem.fat_g), 0),
        )
        .select_from(MealItem)
        .join(MealLog, MealItem.meal_log_id == MealLog.id)
        .filter(MealLog.user_id == user_id, MealLog.date >= start_date, MealLog.date <= today)
        .one()
    )
    return {
        'calories': calories / days,
        'protein_g': protein_g / days,
        'carbs_g': carbs_g / days,
        'fat_g': fat_g / days,
    }

def calculate_bmi(weight_kg, height_m):
    """Calculates BMI given weight in kilograms and height in meters. Requires that `0 < weight_kg < 635` and `0 < height_m < 2.72`."""
    assert 0 < weight_kg < 635
    assert 0 < height_m < 2.72
    bmi = weight_kg / (height_m ** 2)
    return round(bmi, 2)

def calculate_bmr(weight_kg, height_m, age, gender):
    assert 0 < weight_kg <= 635
    assert 0 < height_m <= 2.72
    assert 1 <= age <= 120

    if gender == 'male':
        bmr = (10 * weight_kg) + (6.25 * height_m * 100) - (5 * age) + 5
    elif gender == 'female':
        bmr = (10 * weight_kg) + (6.25 * height_m * 100) - (5 * age) - 161
    
    return bmr

def calculate_tdee(bmr, activity_level):
    if activity_level == 'sedentary':
        return bmr * 1.2
    elif activity_level == 'lightly_active':
        return bmr * 1.375
    elif activity_level == 'moderately_active':
        return bmr * 1.55
    else: # 'very_active'
        return bmr * 1.725

# Lowest daily intake generally advised without medical supervision
MIN_DAILY_CALORIES = {'male': 1500, 'female': 1200}
KCAL_PER_KG = 7700  # approximate energy in 1 kg of body weight

def bmi_category(bmi):
    """Standard adult BMI categories."""
    if bmi < 18.5:
        return 'Underweight'
    if bmi < 25:
        return 'Normal weight'
    if bmi < 30:
        return 'Overweight'
    return 'Obesity'

def _round_to_10(value):
    return int(round(value / 10) * 10)

def _weekly_change_kg(daily_calories_difference):
    return round(abs(daily_calories_difference) * 7 / KCAL_PER_KG, 2)

def calorie_suggestions(tdee, gender, age, bmi):
    """Daily calorie ranges for maintaining, losing, and gaining weight, based on TDEE.

    Returns {'maintain': {...}, 'lose': {...} or None, 'gain': {...} or None, 'notes': [...]}.
    Each range has 'low'/'high' calories and, for lose/gain, the expected weekly change in kg.
    Losing is withheld for minors, underweight BMI, or when it would drop below the safe minimum;
    gaining is withheld for minors. `notes` explains anything withheld or adjusted.
    """
    notes = []
    maintain = {'low': _round_to_10(tdee * 0.95), 'high': _round_to_10(tdee * 1.05)}
    result = {'maintain': maintain, 'lose': None, 'gain': None, 'notes': notes}

    if age < 18:
        notes.append('These estimates are designed for adults. If you are under 18, talk to a doctor '
                     'before changing your calorie intake to lose or gain weight.')
        return result

    floor = MIN_DAILY_CALORIES[gender]
    category = bmi_category(bmi)

    # Losing: 250-750 calories/day below TDEE, never below the safe minimum
    lose_high = _round_to_10(tdee - 250)
    if category == 'Underweight':
        notes.append('Your BMI is in the underweight range, so a calorie deficit is not recommended.')
    elif lose_high <= floor:
        notes.append(f'Your maintenance calories are close to the {floor:,} calories/day minimum generally '
                     'advised without medical supervision, so a calorie deficit is not suggested.')
    else:
        lose_low = max(_round_to_10(tdee - 750), floor)
        if lose_low == floor and _round_to_10(tdee - 750) < floor:
            notes.append(f'The lower end of the weight-loss range is held at {floor:,} calories/day, '
                         'the minimum generally advised without medical supervision.')
        result['lose'] = {
            'low': lose_low, 'high': lose_high,
            'kg_week_low': _weekly_change_kg(tdee - lose_high),
            'kg_week_high': _weekly_change_kg(tdee - lose_low),
        }

    # Gaining: 250-500 calories/day above TDEE
    gain_low, gain_high = _round_to_10(tdee + 250), _round_to_10(tdee + 500)
    result['gain'] = {
        'low': gain_low, 'high': gain_high,
        'kg_week_low': _weekly_change_kg(gain_low - tdee),
        'kg_week_high': _weekly_change_kg(gain_high - tdee),
    }
    if category in ('Overweight', 'Obesity'):
        notes.append('Your BMI is above the normal range, so weight gain is generally not advised unless a '
                     'healthcare professional recommends it (for example, to build muscle).')

    return result