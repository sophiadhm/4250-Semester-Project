from functools import wraps
from flask import redirect, url_for, flash
from flask_login import current_user

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.is_admin == False:
            flash("Access denied. Administrator role required.")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function