# Custom decorator for Flask route protection
# Restricts access to routes that require admin privileges

from functools import wraps
from flask import redirect, url_for, flash
from flask_login import current_user

def admin_required(f):
    """
    Decorator to protect Flask routes so only admin users can access them.

    Usage:
        @app.route('/admin-page')
        @admin_required
        def admin_page():
            ...

    Behavior:
        - Checks if current user is authenticated AND has admin role
        - If not authorized: redirects to login page and shows error message
        - If authorized: allows route handler to execute normally
    """
    @wraps(f)  # Preserve original function name and docstring
    def decorated_function(*args, **kwargs):
        # Check if user is authenticated AND has is_admin flag set
        if not current_user.is_authenticated or not current_user.is_admin:
            # Show error message to user
            flash("Access denied. Administrator role required.")
            # Redirect to login page
            return redirect(url_for('login'))
        # User is authorized - execute the original route handler
        return f(*args, **kwargs)
    return decorated_function
