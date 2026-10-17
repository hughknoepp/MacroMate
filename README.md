# MacroMate

A web app for tracking what you eat. Search the USDA food database, log foods by weight, and see your daily calories, protein, carbs and fat, plus rolling averages. A built-in calculator turns your body measurements into BMI, BMR and TDEE, and suggests calorie ranges for losing, maintaining or gaining weight.

Built with Flask, SQLite and the [USDA FoodData Central](https://fdc.nal.usda.gov/) API.

## Features

**Food logging**
- Search thousands of foods through the USDA FoodData Central API.
- Log any food by weight in grams. Calories, protein, carbs and fat are scaled from the USDA's per-100 g values.
- See any day's logged items and macro totals. Today is at `/log`, and any past day is at `/log/YYYY-MM-DD`.
- Under the main totals, in smaller print, see sugars, calcium, sodium, iron and the essential vitamins (A, C, D, E, K and the B vitamins: thiamin, riboflavin, niacin, pantothenic acid, B6, folate and B12). The USDA doesn't report every nutrient for every food (packaged foods often list only sugars, minerals and vitamins A, C and D), so a nutrient no logged food reports shows a dash, and one only some foods report is starred because its total may be low.
- Get rolling averages (1 to 365 days) of calories, protein, carbs and fat. Days with nothing logged count as zero.

**Personal info calculator**
- Enter gender, age, weight, height (metric or imperial) and activity level. Every field is required, with exactly one choice per option group.
- Shows your **BMI** with its category, your **BMR** (Mifflin-St Jeor equation) and your **TDEE** (BMR x activity factor).
- Suggests daily calorie ranges to **lose** (250-750 below TDEE), **maintain** (TDEE +/- 5%) or **gain** (250-500 above TDEE), with the expected weekly weight change.
- Built-in safeguards: no weight-loss range for an underweight BMI or for under-18s, and never below 1,500 calories/day for men or 1,200 for women.
- A "how these numbers are calculated" section explains every formula on the page. Results are estimates, not medical advice.
- Your details are kept only in your login session (not in the database), so the recommendation pages can use them. They are cleared when you log out.
- Links under the calorie suggestions open **protein, carb and fat recommendations**, with daily grams for each goal (lose, maintain, gain). They share one calorie budget so the three fit together:
  - **Protein** is based on your weight, activity level and age (using an adjusted weight at a BMI of 30 or more).
  - **Fats** are 20-35% of calories, with the most saturated fat that stays under 10%.
  - **Carbs** are what is left after protein and fat (never above 65% of calories or below 130 g), plus a fiber target (14 g per 1,000 calories) and an added-sugar limit (under 10% of calories).
  - None are given for under-18s. Each page explains how its numbers are worked out.

**Accounts**
- Register, log in and log out. Passwords are stored hashed, and every page except the welcome page, login and register requires an account.
- After logging in you return to the page you originally asked for.

## Requirements

- **Python 3.13** (what it is developed and tested with)
- A free **USDA FoodData Central API key**: [sign up here](https://fdc.nal.usda.gov/api-key-signup/). Without one the app still runs, but searching for and logging foods shows a "try again later" message.
- The packages in `requirements.txt`: Flask, Flask-Login, Flask-SQLAlchemy (SQLAlchemy 2), requests, requests-cache and python-dotenv.

## Setup

```bash
git clone https://github.com/hughknoepp/MacroMate.git
cd MacroMate/my-flask-app-1

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # then edit .env (see Configuration)
python app.py
```

Open **http://127.0.0.1:5050**. The database is created automatically on first run.

> The app uses port **5050** because on macOS port 5000 is taken by AirPlay Receiver. Use `127.0.0.1` rather than `localhost`.

Run the tests (67 unit tests covering the request pipeline, nutrient extraction and the protein, carb and fat recommendations) from `my-flask-app-1/`:

```bash
python -m unittest discover -v
```

## Configuration

| Setting | Where | Purpose |
|---|---|---|
| `USDA_API_KEY` | `.env` | Your USDA API key. |
| `SECRET_KEY` | `.env` | Signs login sessions. Use a long random value (`python -c "import secrets; print(secrets.token_hex(32))"`). The built-in default is for development only. |
| `APP_NAME` | `config.py` | The app's name, shown in page titles, the nav bar and the home page. |
| Port | `app.py` (last line) | Defaults to 5050. |

`.env` is git-ignored, so your keys are never committed. `.env.example` is the template.

## Pages

| URL | Method | What it does |
|---|---|---|
| `/` | GET | Welcome page |
| `/register`, `/login`, `/logout` | GET, POST | Account pages |
| `/dashboard` | GET | Your home after login |
| `/foods/search?q=apple` | GET | Search foods |
| `/foods/<fdc_id>/log` | POST | Log a food (the form on the search results) |
| `/log`, `/log/<YYYY-MM-DD>` | GET | Items and macro totals for a day |
| `/log/averages?days=7` | GET | Rolling averages |
| `/log/items/<id>/delete` | POST | Remove a logged item (see Known limitations) |
| `/personal-info` | GET, POST | BMI, BMR, TDEE and calorie suggestions |
| `/recommendations/protein`, `/recommendations/carbs`, `/recommendations/fats` | GET | Daily targets for each macronutrient (need your personal info first) |

Earlier URLs (`/log/search`, `/log/summary/...`) still work and redirect permanently to the ones above.

## How it works

- **Data model** (`models.py`): `User` has `MealLog`s (one per user per date, enforced by a database constraint), and each `MealLog` has `MealItem`s (food, grams, calories, protein, carbs, fat, plus the sugars, minerals and vitamins the USDA reported for it). Existing databases are upgraded automatically at startup.
- **USDA lookups** (`usda.py`, `pipeline.py`): responses are cached on disk in `usda_cache.sqlite` (search results for 6 hours, a food's nutrient record for 30 days, and your API key is never stored in the cache). Logging a food runs two dependent steps in order, fetching the record and then reading its nutrients. Brief network or server errors are retried, and any failure shows a friendly message instead of an error page.
- **Calculations** (`nutrition.py`): daily totals, rolling averages (one database query each), BMI, BMR, TDEE and the calorie suggestions.

```
my-flask-app-1/
├── app.py            routes and request handling
├── models.py         database models and startup upgrades
├── nutrition.py      nutrition and body-metric calculations
├── micronutrients.py sugars, minerals and vitamins: what is tracked and how it is read
├── macros.py         protein, carb and fat recommendations (built to fit together)
├── usda.py           cached USDA API client
├── pipeline.py       runs dependent requests in order, with retries
├── config.py         settings (reads .env)
├── templates/        Jinja2 pages
├── static/style.css  styling
└── tests/            unit tests
```

## Notes and known limitations

- **Development server only.** `app.py` runs Flask with `debug=True`. Do not expose it publicly as is.
- **Database location.** In a standard setup (`.venv` folder) the SQLite database is `instance/app.db`. If you instead create the virtual environment in the project folder itself, Flask puts it at `var/app-instance/app.db`, so deleting that folder (for example, to rebuild the environment) would delete your data.
- **No delete button yet.** The remove-item route exists, but no page links to it.
- **Personal info isn't linked from the dashboard.** Open `/personal-info` directly.
- **No CSRF protection** on forms, and logout is a plain link (GET).
- **Averages are macros only.** Rolling averages cover calories, protein, carbs and fat, not the sugars, minerals and vitamins.
- **Units.** Food nutrition comes from the USDA per 100 g, so foods are logged in grams only.
