from flask import Flask, render_template, redirect, url_for, request, flash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from config import Config
from models import db, User, MealLog, MealItem
from usda import search_food, get_food_details
from datetime import datetime, date as date_type
from nutrition import (get_daily_totals, get_rolling_average, calculate_bmi, calculate_bmr,
                       calculate_tdee, bmi_category, calorie_suggestions)
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
    return User.query.get(int(user_id))

with app.app_context():
    db.create_all()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        if User.query.filter_by(username=username).first():
            flash('Username already exists')
            return redirect(url_for('register'))
        
        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

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

PERSONAL_INFO_FIELDS = ('gender', 'age', 'unit_system', 'weight', 'height', 'activity_level')
PERSONAL_INFO_CHOICES = {
    'gender': {'male', 'female'},
    'unit_system': {'metric', 'imperial'},
    'activity_level': {'sedentary', 'lightly_active', 'moderately_active', 'very_active'},
}

@app.route('/personal-info', methods=['GET', 'POST'])
@login_required
def personal_info():
    bmi = bmr = tdee = None
    category = suggestions = None
    selected_unit = 'metric'
    gender = age = weight = height = activity_level = ''

    if request.method == 'POST':
        # Every field is required, and each must be submitted exactly once, so a
        # radio group can't carry more than one choice (the browser enforces this
        # too, but requests can be crafted by hand).
        values = {}
        for field in PERSONAL_INFO_FIELDS:
            submitted = [v.strip() for v in request.form.getlist(field)]
            if not submitted or not submitted[0]:
                flash('All fields are required.')
                return redirect(url_for('personal_info'))
            if len(submitted) > 1:
                flash(f"Please select only one option for {field.replace('_', ' ')}.")
                return redirect(url_for('personal_info'))
            values[field] = submitted[0]

        for field, choices in PERSONAL_INFO_CHOICES.items():
            if values[field] not in choices:
                flash(f"Invalid selection for {field.replace('_', ' ')}.")
                return redirect(url_for('personal_info'))

        try:
            age_value = int(values['age'])
            weight_value = float(values['weight'])
            height_value = float(values['height'])
        except ValueError:
            flash('Age must be a whole number, and weight and height must be numbers.')
            return redirect(url_for('personal_info'))

        if not 1 <= age_value <= 120:
            flash('Age must be between 1 and 120.')
            return redirect(url_for('personal_info'))

        selected_unit = values['unit_system']
        if selected_unit == 'imperial':
            weight_kg = weight_value * 0.453592
            height_m = height_value * 0.0254
        else:
            weight_kg = weight_value
            height_m = height_value

        # BMR and TDEE are calculated in metric units, so use the converted values.
        # The calculators assert on out-of-range input, hence the AssertionError catch.
        try:
            bmi = calculate_bmi(weight_kg, height_m)
            bmr = calculate_bmr(weight_kg, height_m, age_value, values['gender'])
            tdee = calculate_tdee(bmr, values['activity_level'])
        except AssertionError:
            flash('Invalid weight or height values. Please ensure they are within reasonable ranges.')
            return redirect(url_for('personal_info'))

        if tdee <= 0:
            flash('Those values give an unrealistic calorie estimate. Please check your entries.')
            return redirect(url_for('personal_info'))
        # Whole calories/day, rounding halves up. TDEE is worked out from the unrounded BMR.
        bmr = int(bmr + 0.5)
        tdee = int(tdee + 0.5)

        category = bmi_category(bmi)
        suggestions = calorie_suggestions(tdee, values['gender'], age_value, bmi)

        # Hand the submitted values back so the form keeps them
        gender, activity_level = values['gender'], values['activity_level']
        age, weight, height = age_value, weight_value, height_value

    return render_template('personal_info.html', bmi=bmi, bmi_category=category, bmr=bmr, tdee=tdee,
                           suggestions=suggestions, selected_unit=selected_unit,
                           gender=gender, age=age, weight=weight, height=height,
                           activity_level=activity_level)

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

def extract_nutrients(food_detail):
    """Pull the four tracked nutrients (per 100g) out of a USDA food record."""
    values = {}
    for field, (name, unit) in NUTRIENT_MAP.items():
        values[field] = None
        for n in food_detail.get('foodNutrients', []):
            nutrient = n.get('nutrient', {})
            if nutrient.get('name') == name and nutrient.get('unitName', '').upper() == unit:
                values[field] = n.get('amount')
                break
    return values

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
    
    try:
        food = get_food_details(fdc_id)
    except requests.exceptions.RequestException:
        flash('Could not fetch food details. Please try again later.')
        return redirect(url_for('food_search'))
    per_100g = extract_nutrients(food)
    scale = quantity_g / 100

    meal_log = MealLog.query.filter_by(
        user_id=current_user.id, date=date_type.today()
    ).first()
    if meal_log is None:
        meal_log = MealLog(user_id=current_user.id, date=date_type.today())
        db.session.add(meal_log)
        db.session.flush()
    
    item = MealItem(
        meal_log_id = meal_log.id,
        food_name = food.get('description', 'Unknown food'),
        fdc_id = fdc_id,
        quantity_g = quantity_g,
        calories = (per_100g['calories'] or 0) * scale,
        protein_g = (per_100g['protein_g'] or 0) * scale,
        carbs_g = (per_100g['carbs_g'] or 0) * scale,
        fat_g = (per_100g['fat_g'] or 0) * scale,
    )
    db.session.add(item)
    db.session.commit()

    flash(f"Added {item.food_name} to today's log")
    return redirect(url_for('dashboard'))

MAX_AVERAGE_DAYS = 365

def summary_context(parsed_date):
    """Everything summary.html needs to render one day's totals and items."""
    totals = get_daily_totals(current_user.id, parsed_date)
    meal_log = MealLog.query.filter_by(user_id=current_user.id, date=parsed_date).first()
    items = meal_log.items if meal_log else []
    return {'totals': totals, 'date': parsed_date, 'items': items}

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
    item = MealItem.query.get(item_id)
    if item is None:
        return False
    if item.meal_log.user_id != user_id:
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