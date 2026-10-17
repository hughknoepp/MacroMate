"""Checking and converting the details people enter on the Edit Personal Information page."""
from macros import KG_PER_LB

M_PER_IN = 0.0254

FIELDS = ('gender', 'age', 'unit_system', 'weight', 'height', 'activity_level')
CHOICES = {
    'gender': {'male', 'female'},
    'unit_system': {'metric', 'imperial'},
    'activity_level': {'sedentary', 'lightly_active', 'moderately_active', 'very_active'},
}


def parse_form(form):
    """Check submitted details. Returns (values, None) if they are fine, or (None, message) if not.

    `form` is a MultiDict like request.form. Every field is required, and each must be submitted
    exactly once, so a group of radio buttons can't carry more than one choice (the browser
    enforces this too, but requests can be crafted by hand). `values` has age as an int and weight
    and height as floats, still in the unit system the person chose.
    """
    values = {}
    for field in FIELDS:
        submitted = [v.strip() for v in form.getlist(field)]
        if not submitted or not submitted[0]:
            return None, 'All fields are required.'
        if len(submitted) > 1:
            return None, f"Please select only one option for {field.replace('_', ' ')}."
        values[field] = submitted[0]

    for field, choices in CHOICES.items():
        if values[field] not in choices:
            return None, f"Invalid selection for {field.replace('_', ' ')}."

    try:
        values['age'] = int(values['age'])
        values['weight'] = float(values['weight'])
        values['height'] = float(values['height'])
    except ValueError:
        return None, 'Age must be a whole number, and weight and height must be numbers.'

    if not 1 <= values['age'] <= 120:
        return None, 'Age must be between 1 and 120.'
    return values, None


def metric_values(unit_system, weight, height):
    """(weight in kg, height in m) from weight and height in the given unit system."""
    if unit_system == 'imperial':
        return weight * KG_PER_LB, height * M_PER_IN
    return weight, height
