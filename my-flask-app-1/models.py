from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date as date_type
from sqlalchemy import func, inspect, text

db = SQLAlchemy()

class User(UserMixin, db.Model):
    """Each User has an ID, username, email, and password (hashed for privacy & security)"""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class MealLog(db.Model):
    """Each MealLog instance has an associated id, user_id (from User),
    date, and items (from MealItem, this includes food details).
    A user has at most one MealLog per date (enforced by the database)."""
    __table_args__ = (db.UniqueConstraint('user_id', 'date', name='uq_meal_log_user_date'),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, default=date_type.today, nullable=False)
    items = db.Relationship('MealItem', backref='meal_log', cascade='all, delete-orphan')

class MealItem(db.Model):
    """Each MealItem instance has an associated id, meal_log_id (from MealLog), 
    food name, FDC ID, # grams, calories, protein(g), fat(g), carbs(g)"""
    id = db.Column(db.Integer, primary_key=True)
    # Indexed: every lookup of a log's items goes through this column
    meal_log_id = db.Column(db.Integer, db.ForeignKey('meal_log.id'), nullable=False, index=True)
    food_name = db.Column(db.String(200), nullable=False)
    fdc_id = db.Column(db.Integer, nullable=False)
    quantity_g = db.Column(db.Float, nullable=False)
    calories = db.Column(db.Float)
    protein_g = db.Column(db.Float)
    carbs_g = db.Column(db.Float)
    fat_g = db.Column(db.Float)
    # Sugars, minerals and vitamins for the portion eaten, e.g. {'calcium_mg': 12.5}. Only the
    # nutrients the USDA reported are present. NULL for items logged before this was tracked.
    micronutrients = db.Column(db.JSON)

def ensure_meal_log_uniqueness():
    """Make sure the meal_log table enforces one log per (user, date).

    db.create_all() only builds tables that don't exist yet, so a database created before
    the constraint was added would never get it. This upgrades such a database: any
    duplicate logs are merged into the oldest one (their items move over, nothing is lost),
    then a unique index is added. It does nothing if the rule is already in place, so it is
    safe to run on every startup. Needs an application context.
    """
    columns = sorted(['user_id', 'date'])
    inspector = inspect(db.engine)
    if not inspector.has_table('meal_log'):
        return  # create_all() will build it, constraint included

    already_enforced = (
        any(sorted(c['column_names']) == columns for c in inspector.get_unique_constraints('meal_log'))
        or any(i.get('unique') and sorted(i['column_names']) == columns for i in inspector.get_indexes('meal_log'))
    )
    if already_enforced:
        return

    duplicated = (db.session.query(MealLog.user_id, MealLog.date)
                  .group_by(MealLog.user_id, MealLog.date)
                  .having(func.count(MealLog.id) > 1).all())
    for user_id, day in duplicated:
        ids = [row[0] for row in db.session.query(MealLog.id)
               .filter_by(user_id=user_id, date=day).order_by(MealLog.id)]
        keep, extras = ids[0], ids[1:]
        MealItem.query.filter(MealItem.meal_log_id.in_(extras)).update(
            {'meal_log_id': keep}, synchronize_session=False)
        MealLog.query.filter(MealLog.id.in_(extras)).delete(synchronize_session=False)
    db.session.commit()

    db.session.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS uq_meal_log_user_date '
                            'ON meal_log (user_id, date)'))
    db.session.commit()


def ensure_meal_item_index():
    """Add the index on meal_item.meal_log_id to databases created before it existed.

    New databases get it from the model (index=True); create_all() never alters existing
    tables. Harmless to run on every startup. Needs an application context.
    """
    db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_meal_item_meal_log_id '
                            'ON meal_item (meal_log_id)'))
    db.session.commit()


def ensure_micronutrients_column():
    """Add meal_item.micronutrients to databases created before it existed.

    New databases get it from the model; create_all() never alters existing tables. Items
    already logged keep NULL there (they have no micronutrient data). Safe to run on every
    startup. Needs an application context.
    """
    if 'micronutrients' not in {c['name'] for c in inspect(db.engine).get_columns('meal_item')}:
        db.session.execute(text('ALTER TABLE meal_item ADD COLUMN micronutrients JSON'))
        db.session.commit()
