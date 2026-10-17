from flask import Flask, render_template, redirect, url_for, request, flash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from config import Config
from models import (db, User, MealLog, MealItem, Profile, save_profile, ensure_meal_log_uniqueness,
                    ensure_meal_item_index, ensure_micronutrients_column)
from personal_details import FIELDS as PERSONAL_FIELDS, parse_form as parse_personal_details, metric_values
from micronutrients import (extract_micronutrients, scale_micronutrients, micronutrient_totals,
                            group_rows, format_amount)
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from usda import search_food, get_food_details
from pipeline import RequestPipeline
from macros import (protein_recommendations as build_protein_recommendations,
                    carb_recommendations as build_carb_recommendations,
                    fat_recommendations as build_fat_recommendations, KG_PER_LB)
from datetime import datetime, date as date_type
from nutrition import (get_daily_items, totals_from_items, get_rolling_average, calculate_bmi,
                       calculate_bmr, calculate_tdee, bmi_category, calorie_suggestions)
import requests
from werkzeug.routing import BaseConverter, ValidationError

class DateConverter(BaseConverter):
    """URL converter for ISO dates, e.g. /log/2026-10-11. Impossible dates give a 404."""
    regex = r'\d{4}-\d{2}-\d{2}'

    def to_python(self, value):
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except ValueError:
            raise ValidationError()

    def to_url(self, value):
        return value.isoformat() if isinstance(value, date_type) else str(value)

app = Flask(__name__)
app.config.from_object(Config)

@app.context_processor
def inject_app_name():
    """Make {{ app_name }} available in every template."""
    return {'app_name': app.config['APP_NAME']}

app.url_map.converters['date'] = DateConverter
db.init_app(app)

@app.before_request
def redirect_trailing_slash():
    """Every URL has one canonical form with no trailing slash: /login/ -> /login."""
    if request.path != '/' and request.path.endswith('/'):
        canonical = request.path.rstrip('/') or '/'
        if request.query_string:
            canonical += '?' + request.query_string.decode()
        return redirect(canonical, code=308)  # 308 keeps the HTTP method

def is_safe_redirect_target(target):
    """True only for a plain path on this site, like /log/search (prevents open redirects).

    Anything that could be read as another host is refused: absolute URLs, '//host' and
    '///host', backslashes, and control characters (browsers strip tabs/newlines from URLs,
    so '/<TAB>/host' would otherwise turn into '//host').
    """
    return (bool(target) and target.isprintable() and target.startswith('/')
            and not target.startswith('//') and '\\' not in target)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

with app.app_context():
    db.create_all()
    ensure_meal_log_uniqueness()
    ensure_meal_item_index()
    ensure_micronutrients_column()

@app.route('/')
def home():
    return render_template('index.html')

def registration_conflict(username, email):
    """A message explaining why this username/email can't be registered, or None if it's free.

    Emails are compared ignoring upper/lower case, so Sam@x.com and sam@x.com count as the same.
    """
    if User.query.filter_by(username=username).first():
        return 'Username already exists'
    if User.query.filter(func.lower(User.email) == email.lower()).first():
        return 'That email is already registered. Try logging in instead.'
    return None

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email'].strip()
        password = request.form['password']

        conflict = registration_conflict(username, email)
        if conflict:
            flash(conflict)
            return redirect(url_for('register'))
        
        user = User(username=username, email=email)
        user.set_password(password)
        try:
            db.session.add(user)
            db.session.commit()
        except IntegrityError:
            # Someone registered the same username/email between our check and the save
            db.session.rollback()
            flash(registration_conflict(username, email) or 'Could not create your account. Please try again.')
            return redirect(url_for('register'))

        flash('Registration successful! Please log in')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    # Flask-Login sends people here as /login?next=/some/page; go back there afterwards
    next_url = request.args.get('next')
    if not is_safe_redirect_target(next_url):
        next_url = None

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            flash('Login successful!')
            return redirect(next_url or url_for('dashboard'))
        else:
            flash('Invalid username or password')
            return redirect(url_for('login', next=next_url))

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.')
    return redirect(url_for('home'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', user=current_user)

def body_metrics(weight_kg, height_m, age, gender, activity_level):
    """BMI, BMR and TDEE (BMR and TDEE as whole calories/day, halves rounding up).

    TDEE is worked out from the unrounded BMR. Raises AssertionError if the measurements are
    out of range and ValueError if they give an unrealistic (zero or negative) calorie estimate.
    """
    bmi = calculate_bmi(weight_kg, height_m)
    bmr = calculate_bmr(weight_kg, height_m, age, gender)
    tdee = calculate_tdee(bmr, activity_level)
    if tdee <= 0:
        raise ValueError('unrealistic calorie estimate')
    return bmi, int(bmr + 0.5), int(tdee + 0.5)

def load_profile():
    """The logged-in user's saved personal details, or None if they haven't saved any (or what is
    saved no longer adds up). Returned as a dict: what was typed (weight, height, in the chosen
    unit system), the same in metric (weight_kg, height_m), and when it was last saved."""
    row = Profile.query.filter_by(user_id=current_user.id).first()
    if row is None:
        return None
    weight_kg, height_m = metric_values(row.unit_system, row.weight, row.height)
    try:
        body_metrics(weight_kg, height_m, row.age, row.gender, row.activity_level)
    except (AssertionError, ValueError):
        return None
    return {'gender': row.gender, 'age': row.age, 'unit_system': row.unit_system, 'weight': row.weight,
            'height': row.height, 'weight_kg': weight_kg, 'height_m': height_m,
            'activity_level': row.activity_level, 'updated_on': row.updated_on}

def details_out_of_date(profile):
    """Age is saved as a number, so after a year it may be wrong: ask the person to check it."""
    return (date_type.today() - profile['updated_on']).days > 365

def profile_texts(profile):
    """Weight, height and activity as short text, in the unit system the person chose."""
    imperial = profile['unit_system'] == 'imperial'
    return {'weight_text': f"{profile['weight']:g} {'lb' if imperial else 'kg'}",
            'height_text': f"{profile['height']:g} {'in' if imperial else 'm'}",
            'activity_label': ACTIVITY_LABELS[profile['activity_level']]}

def need_personal_info(message='Add your personal information first, and then you can see your recommendations.'):
    flash(message)
    return redirect(url_for('edit_personal_info'))

@app.route('/personal-info')
@login_required
def personal_info():
    """Your saved details, with your BMI, BMR, TDEE and calorie suggestions."""
    profile = load_profile()
    if profile is None:
        return need_personal_info('Add your personal information to see your calorie and nutrient numbers.')
    bmi, bmr, tdee = body_metrics(profile['weight_kg'], profile['height_m'], profile['age'],
                                  profile['gender'], profile['activity_level'])
    suggestions = calorie_suggestions(tdee, profile['gender'], profile['age'], bmi)
    return render_template('personal_info.html', profile=profile, bmi=bmi, bmi_category=bmi_category(bmi),
                           bmr=bmr, tdee=tdee, suggestions=suggestions, selected_unit=profile['unit_system'],
                           out_of_date=details_out_of_date(profile), **profile_texts(profile))

@app.route('/personal-info/edit', methods=['GET', 'POST'])
@login_required
def edit_personal_info():
    """The form for entering or changing your personal details. They are saved to your account."""
    saved = load_profile()
    if request.method == 'POST':
        values, error = parse_personal_details(request.form)
        if error is None:
            weight_kg, height_m = metric_values(values['unit_system'], values['weight'], values['height'])
            try:
                body_metrics(weight_kg, height_m, values['age'], values['gender'], values['activity_level'])
            except AssertionError:
                error = 'Invalid weight or height values. Please ensure they are within reasonable ranges.'
            except ValueError:
                error = 'Those values give an unrealistic calorie estimate. Please check your entries.'
        if error is None:
            save_profile(current_user.id, values)
            flash('Your personal information was saved.')
            return redirect(url_for('personal_info'))
        # Show the form again with what was typed, so nothing has to be re-entered
        flash(error)
        form = {field: request.form.get(field, '') for field in PERSONAL_FIELDS}
        unit = form['unit_system'] if form['unit_system'] in ('metric', 'imperial') else 'metric'
        return render_template('edit_personal_info.html', saved=saved, selected_unit=unit,
                               out_of_date=False, **{k: v for k, v in form.items() if k != 'unit_system'}), 400

    if saved is None:
        form, unit = dict.fromkeys(('gender', 'age', 'weight', 'height', 'activity_level'), ''), 'metric'
    else:
        form = {'gender': saved['gender'], 'age': saved['age'], 'weight': f"{saved['weight']:g}",
                'height': f"{saved['height']:g}", 'activity_level': saved['activity_level']}
        unit = saved['unit_system']
    return render_template('edit_personal_info.html', saved=saved, selected_unit=unit,
                           out_of_date=saved is not None and details_out_of_date(saved), **form)

ACTIVITY_LABELS = {'sedentary': 'sedentary', 'lightly_active': 'lightly active',
                   'moderately_active': 'moderately active', 'very_active': 'very active'}

def recommendation_inputs():
    """What every nutrient-recommendation page starts from, or None if the person hasn't entered
    their personal information yet. Protein, carbs and fats all begin here, so they are built from
    the same calorie targets and fit together."""
    profile = load_profile()
    if profile is None:
        return None
    bmi, _, tdee = body_metrics(profile['weight_kg'], profile['height_m'], profile['age'],
                                profile['gender'], profile['activity_level'])
    suggestions = calorie_suggestions(tdee, profile['gender'], profile['age'], bmi)
    use_lbs = profile['unit_system'] == 'imperial'
    return {
        'profile': profile, 'bmi': bmi, 'tdee': tdee, 'suggestions': suggestions, 'use_lbs': use_lbs,
        'calorie_ranges': {goal: suggestions[goal] for goal in ('lose', 'maintain', 'gain')},
        **profile_texts(profile),
    }

def protein_for(inputs):
    profile = inputs['profile']
    return build_protein_recommendations(
        profile['weight_kg'], profile['height_m'], profile['age'], profile['activity_level'], inputs['bmi'],
        inputs['calorie_ranges'], inputs['suggestions']['notes'])

@app.route('/recommendations/protein')
@login_required
def protein_recommendations():
    inputs = recommendation_inputs()
    if inputs is None:
        return need_personal_info()
    recommendation = protein_for(inputs)
    basis_text = (None if recommendation['basis_kg'] is None else
                  f"{recommendation['basis_kg'] / KG_PER_LB:.0f} lb" if inputs['use_lbs'] else f"{recommendation['basis_kg']:.1f} kg")
    return render_template('protein.html', rec=recommendation, basis_text=basis_text,
                           bmi_category=bmi_category(inputs['bmi']), **inputs)

@app.route('/recommendations/carbs')
@login_required
def carbs_recommendations():
    inputs = recommendation_inputs()
    if inputs is None:
        return need_personal_info()
    # Carbs are what is left after protein and fat, so they are built from the protein targets
    recommendation = build_carb_recommendations(inputs['profile']['age'], inputs['calorie_ranges'],
                                                protein_for(inputs)['goals'], inputs['suggestions']['notes'])
    return render_template('carbs.html', rec=recommendation, **inputs)

@app.route('/recommendations/fats')
@login_required
def fats_recommendations():
    inputs = recommendation_inputs()
    if inputs is None:
        return need_personal_info()
    recommendation = build_fat_recommendations(inputs['profile']['age'], inputs['calorie_ranges'],
                                               inputs['suggestions']['notes'])
    return render_template('fats.html', rec=recommendation, **inputs)

@app.route('/foods/search')
@login_required
def food_search():
    query = request.args.get('q', '')
    results = []
    if query:
        try:
            results = search_food(query)
        except requests.exceptions.RequestException:
            flash('Food search is unavailable right now. Please try again later.')
    return render_template('food_search.html', results=results)

NUTRIENT_MAP = {
    'calories': ('Energy', 'KCAL'),
    'protein_g': ('Protein', 'G'),
    'carbs_g': ('Carbohydrate, by difference', 'G'),
    'fat_g': ('Total lipid (fat)', 'G'),
}

# (nutrient name, unit) -> our field name, so one pass over the record can find all four
NUTRIENT_FIELDS = {name_unit: field for field, name_unit in NUTRIENT_MAP.items()}

def extract_nutrients(food_detail):
    """Pull the four tracked nutrients (per 100g) out of a USDA food record.

    One pass over the record's nutrient list (these can run to a hundred entries or more).
    If a nutrient is listed more than once, the first entry wins.
    """
    values = dict.fromkeys(NUTRIENT_MAP)
    found = set()
    for n in food_detail.get('foodNutrients', []):
        nutrient = n.get('nutrient', {})
        field = NUTRIENT_FIELDS.get((nutrient.get('name'), nutrient.get('unitName', '').upper()))
        if field is not None and field not in found:
            values[field] = n.get('amount')
            found.add(field)
            if len(found) == len(NUTRIENT_MAP):
                break  # nothing left to find
    return values

def get_or_create_meal_log(user_id, day):
    """The user's MealLog for `day`, created if it doesn't exist yet.

    The database allows only one log per (user, date). If two requests both find none and
    both try to create it, the second insert is refused; we then discard that attempt and
    use the log the first request created. Call this before adding anything else to the
    session, since the rollback would discard it too.
    """
    meal_log = MealLog.query.filter_by(user_id=user_id, date=day).first()
    if meal_log is not None:
        return meal_log
    try:
        meal_log = MealLog(user_id=user_id, date=day)
        db.session.add(meal_log)
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        meal_log = MealLog.query.filter_by(user_id=user_id, date=day).one()
    return meal_log

class NoNutritionData(Exception):
    """The USDA record has none of the nutrients we track."""

def require_nutrients(food_detail):
    values = extract_nutrients(food_detail)
    if all(v is None for v in values.values()):
        raise NoNutritionData()
    return values

# Looking up a food takes two dependent steps: the nutrients can't be read until the
# record has been fetched, and the record can't be fetched without the fdcId. The
# pipeline runs them in order, retries brief network/server hiccups on the fetch, and
# stops at the first failure. Build once, reuse for every request.
FOOD_LOOKUP = (RequestPipeline()
               .step('details', lambda r: get_food_details(r['fdc_id']), retries=2)
               .step('nutrients', lambda r: require_nutrients(r['details']))
               .step('micronutrients', lambda r: extract_micronutrients(r['details'])))

FOOD_LOOKUP_ERRORS = {
    'details': 'Could not fetch food details. Please try again later.',
    'nutrients': 'The USDA has no nutrition data for that food, so it was not logged.',
}

@app.route('/foods/<int:fdc_id>/log', methods=['POST'])
@login_required
def add_food(fdc_id):
    try:
        quantity_g = float(request.form['quantity_g'])
    except (KeyError, ValueError):
        flash('Enter a valid quantity in grams')
        return redirect(url_for('food_search'))
    
    if quantity_g <= 0:
        flash('Quantity must be greater than zero')
        return redirect(url_for('food_search'))
    
    lookup = FOOD_LOOKUP.run(fdc_id=fdc_id)
    if not lookup.ok:
        app.logger.warning('Food lookup for fdcId %s failed at step %r: %r',
                           fdc_id, lookup.failed_step, lookup.error)
        flash(FOOD_LOOKUP_ERRORS.get(lookup.failed_step, FOOD_LOOKUP_ERRORS['details']))
        return redirect(url_for('food_search'))
    food, per_100g, micro_per_100g = lookup['details'], lookup['nutrients'], lookup['micronutrients']
    scale = quantity_g / 100

    meal_log = get_or_create_meal_log(current_user.id, date_type.today())

    item = MealItem(
        meal_log_id = meal_log.id,
        food_name = food.get('description', 'Unknown food'),
        fdc_id = fdc_id,
        quantity_g = quantity_g,
        calories = (per_100g['calories'] or 0) * scale,
        protein_g = (per_100g['protein_g'] or 0) * scale,
        carbs_g = (per_100g['carbs_g'] or 0) * scale,
        fat_g = (per_100g['fat_g'] or 0) * scale,
        micronutrients = scale_micronutrients(micro_per_100g, scale),
    )
    db.session.add(item)
    db.session.commit()

    flash(f"Added {item.food_name} to today's log")
    return redirect(url_for('dashboard'))

MAX_AVERAGE_DAYS = 365

def summary_context(parsed_date):
    """Everything summary.html needs to render one day's totals and items."""
    items = get_daily_items(current_user.id, parsed_date)  # one query; totals come from these
    return {'totals': totals_from_items(items), 'date': parsed_date, 'items': items,
            'micronutrient_groups': group_rows(micronutrient_totals(items))}

app.add_template_filter(format_amount, 'amount')

@app.route('/log')
@app.route('/log/<date:log_date>')
@login_required
def daily_summary(log_date=None):
    return render_template('summary.html', **summary_context(log_date or date_type.today()))

@app.route('/log/averages')
@login_required
def rolling_average():
    # /log/averages?days=7 -- an optional filter belongs in the query string, not the path
    days = request.args.get('days', type=int, default=0)
    if not 1 <= days <= MAX_AVERAGE_DAYS:
        flash(f'Days must be a whole number from 1 to {MAX_AVERAGE_DAYS}.')
        return redirect(url_for('daily_summary'))

    averages = get_rolling_average(current_user.id, days)
    if not any(averages.values()):
        averages = None  # nothing logged in that window
    return render_template('summary.html', averages=averages, num_days=days,
                           **summary_context(date_type.today()))

def delete_meal_item(item_id, user_id):
    # One query that only matches the item if it belongs to this user's logs
    item = (MealItem.query.join(MealLog)
            .filter(MealItem.id == item_id, MealLog.user_id == user_id)
            .first())
    if item is None:
        return False
    db.session.delete(item)
    db.session.commit()
    return True

@app.route('/log/items/<int:item_id>/delete', methods=['POST'])
@login_required
def remove_food(item_id):
    if delete_meal_item(item_id, user_id=current_user.id):
        flash('Item removed')
    else:
        flash('Could not remove that item')
    return redirect(url_for('daily_summary'))

# --- Legacy URLs ---
# These were the original paths. They permanently redirect to the current ones so that
# old bookmarks and links keep working. (Only GET pages need this; the old POST-only
# URLs were reached through forms, which always use the current URLs.)

@app.route('/log/search')
def legacy_food_search():
    return redirect(url_for('food_search', **request.args.to_dict()), code=301)

@app.route('/log/summary')
def legacy_daily_summary():
    return redirect(url_for('daily_summary'), code=301)

@app.route('/log/summary/<log_date>')
def legacy_daily_summary_for_date(log_date):
    return redirect(url_for('daily_summary', log_date=log_date), code=301)

@app.route('/log/summary/average')
def legacy_rolling_average():
    return redirect(url_for('rolling_average', **request.args.to_dict()), code=301)

@app.route('/log/summary/average/<int:days>')
def legacy_rolling_average_for_days(days):
    return redirect(url_for('rolling_average', days=days), code=301)

if __name__ == '__main__':
    app.run(debug=True, port=5050)