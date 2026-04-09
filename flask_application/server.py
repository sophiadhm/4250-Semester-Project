# Flask web application for assignment management
# Provides web UI for user authentication, assignment management, and calendar integration

import sys
import os

# Automatically find the project root (the folder containing both 'app' and 'flask_application')
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Add it to Python's module search path so we can import from 'app' package
if project_root not in sys.path:
    sys.path.append(project_root)


from flask import Flask, render_template, request, flash, redirect, url_for
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from app.models import db, User, Assignment
import requests
from sqlalchemy import text
from sync import sync_assignments

# Initialize Flask application
app = Flask(__name__)
# Secret key for session management and CSRF protection
app.secret_key = 'key'  # TODO: Use environment variable in production

# FastAPI backend server URL for making requests to assignment API
URL = 'http://127.0.0.1:8000'


# DATABASE CONFIGURATION
# Get project root directory for locating database file
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
# SQLAlchemy configuration for SQLite database
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(BASE_DIR, 'users.db')}"
# Disable automatic tracking of modifications (improves performance)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize Flask-SQLAlchemy database with Flask app
db.init_app(app)
# Create all tables in database context
with app.app_context():
    db.create_all()
    # Note: create_all() doesn't add new columns to existing tables
    # So we patch schema manually if migrations needed
    assignment_cols = db.session.execute(text("PRAGMA table_info(assignments)")).fetchall()
    assignment_col_names = {col[1] for col in assignment_cols}

    # Add user_id column if missing (for assignment ownership tracking)
    if "user_id" not in assignment_col_names:
        db.session.execute(text("ALTER TABLE assignments ADD COLUMN user_id INTEGER"))
        db.session.commit()

    # Add ics_uid column if missing (for calendar sync tracking)
    if "ics_uid" not in assignment_col_names:
        db.session.execute(text("ALTER TABLE assignments ADD COLUMN ics_uid VARCHAR(255)"))
        db.session.commit()

# Setup Flask-Login for user authentication
login_manager = LoginManager(app)
# Redirect unauthenticated users to login page
login_manager.login_view = 'login'
# Set flash message category for login messages
login_manager.login_message_category = 'error'


# ============================================================================
# USER AUTHENTICATION ROUTES
# ============================================================================

# Flask-Login callback to load user object by ID from database
@login_manager.user_loader
def load_user(user_id):
    # Query database for user with given id
    return User.query.get(int(user_id))

# ACCOUNT PAGE - Allows logged-in users to update their password and calendar ICS URL
@app.route("/account", methods=["GET", "POST"])
@login_required  # Require user to be logged in
def account():
    # Handle form submission (POST request)
    if request.method == "POST":
        # Get new password from form (if provided)
        new_password = request.form.get("password")
        # Get ICS calendar URL from form (if provided)
        ics_url = request.form.get("ics_url")

        # Update password if provided
        if new_password:
            current_user.set_password(new_password)

        # Update ICS URL if provided
        if ics_url:
            current_user.ics_url = ics_url

        # Save changes to database
        db.session.commit()
        # Show success message
        flash("Account updated!", "success")
        # Redirect to account page to show updated info
        return redirect(url_for("account"))

    # Handle GET request - show account page
    return render_template("account.html")

# 3 routes -- login, logout, register
# REGISTER PAGE - Allows new users to create an account
@app.route("/register", methods=["GET", "POST"])
def register():
    # Handle form submission (POST request)
    if request.method == "POST":
        # Get username from form
        username = request.form["username"]
        # Get password from form
        password = request.form["password"]
        # Get admin checkbox (checked = 'on')
        is_admin = request.form.get('is_admin') == 'on'  # on means it is checked

        print(username)

        # Check if username already exists in database
        if User.query.filter_by(username=username).first():
            # Username taken - show error and redirect
            flash("Username already exists.", "error")
            return redirect(url_for('register'))

        # Create new user object
        new_user = User(username=username, is_admin=is_admin)
        # Hash the password and store it
        new_user.set_password(password)
        # Add user to database session
        db.session.add(new_user)
        # Save to database
        db.session.commit()

        # Show success message
        flash("Account created successfully!", "success")
        # Redirect to login page
        return redirect(url_for('login'))

    # Handle GET request - show registration form
    return render_template('register.html')

# LOGIN PAGE - Authenticates user credentials and creates session
@app.route('/login', methods=["GET", "POST"])
def login():
    # Handle form submission (POST request)
    if request.method == "POST":
        # Get username from form
        username = request.form['username']
        # Get password from form
        password = request.form['password']

        # Query database for user with matching username
        user = User.query.filter_by(username=username).first()
        # Check if user exists and password is correct
        if user and user.check_password(password):
            # Create authenticated session for user
            login_user(user)

            # If user has a calendar URL, sync assignments from it
            if user.ics_url:
                sync_assignments(user)

            # Show success message
            flash("User logged in successfully!", "success")
            # Redirect to home page
            return redirect(url_for('index'))

        # Invalid credentials
        flash("Invalid username or password.", "error")
        return redirect(url_for("login"))

    # Handle GET request - show login form
    return render_template("login.html")

# LOGOUT - Destroys user session and logs user out
@app.route("/logout")
@login_required  # Require user to be logged in
def logout():
    # Destroy user session
    logout_user()
    # Show logout confirmation
    flash("You have been logged out.", "success")
    # Redirect to login page
    return redirect(url_for("login"))


# ============================================================================
# ASSIGNMENT MANAGEMENT ROUTES
# ============================================================================

# HOME PAGE - Displays user's assignments sorted by due date
@app.route('/')
@login_required  # Require user to be logged in
def index():
    # Query all assignments for current user, sorted by due date
    assignments = Assignment.query.filter_by(user_id=current_user.id).order_by(Assignment.due_date).all()
    # Render template with assignments
    return render_template('index.html', assignments=assignments)


# CREATE NEW ASSIGNMENT - Adds a new assignment to the database
@app.route("/assignments/new", methods=["POST"])
@login_required  # Require user to be logged in
def new_assignment():
    # Build assignment data from form fields
    data = {
        "user_id": current_user.id,  # Set current user as owner
        "name": request.form.get("name"),  # Assignment name
        "course": request.form.get("course"),  # Course name
        "class_color": request.form.get("class_color"),  # UI color (not stored in DB)
        "due_date": request.form.get("due_date"),  # Due date
        "priority_level": request.form.get("priority"),  # Priority level
        "course_id": "0000",  # Default course code
        "due_time": None,  # Not provided in this form
        "assignment_type": None,  # Not provided in this form
        "points": None  # Not provided in this form
    }

    # Send POST request to FastAPI backend to create assignment
    requests.post("http://127.0.0.1:8000/assignments/", json=data)
    # Redirect to home page to show new assignment
    return redirect(url_for("index"))


# ============================================================================
# CALENDAR INTEGRATION ROUTES
# ============================================================================

# CALENDAR PAGE - Displays assignments in calendar view and supports ICS sync
@app.route("/calendar/")
@login_required  # Require user to be logged in
def about():
    # If user has connected a calendar, sync latest assignments from it
    if current_user.ics_url:
        sync_assignments(current_user)

    # Query all assignments for current user, sorted by due date
    raw_assignments = Assignment.query.filter_by(user_id=current_user.id).order_by(Assignment.due_date).all()
    # Convert ORM objects to dictionaries for template rendering
    assignments = [
        {
            'id': a.id,
            'name': a.name,
            'course': a.course,
            'course_id': a.course_id,
            'due_date': a.due_date,
            'due_time': a.due_time,
            'assignment_type': a.assignment_type,
            'priority_level': a.priority_level,
            'points': a.points,
        }
        for a in raw_assignments
    ]
    # Render calendar template with assignments
    return render_template("calendar.html", assignments=assignments)


# CONNECT CALENDAR - Saves user's ICS calendar URL for syncing
@app.route("/connect-calendar/", methods=["GET", "POST"])
@login_required  # Require user to be logged in
def connect_calendar():
    # Get ICS URL from form
    ics_url = request.form.get("ics_url")
    # Save ICS URL to user's account
    current_user.ics_url = ics_url
    # Commit changes to database
    db.session.commit()
    # Show success message
    flash("Calendar connected successfully!", "success")
    # Redirect to calendar page
    return redirect(url_for("about"))

# SYNC ASSIGNMENTS - Manually syncs assignments from user's connected calendar
@app.route("/sync/")
@login_required  # Require user to be logged in
def sync():
    # Fetch latest assignments from user's ICS calendar URL
    sync_assignments(current_user)
    # Show success message
    flash("Assignments synced successfully!", "success")
    # Redirect to home page
    return redirect(url_for("index"))
    return redirect(url_for("assignment"))


# ASSIGNMENTS PAGE - Displays all assignments in a list view
@app.route("/assignments/")
@login_required  # Require user to be logged in
def assignment():
    # Query all assignments for current user, sorted by due date
    assignments = Assignment.query.filter_by(
        user_id=current_user.id
    ).order_by(Assignment.due_date).all()
    # Render template with assignments
    return render_template("assignments.html", assignments=assignments)


# APPLICATION ENTRY POINT
if __name__ == '__main__':
    # Run Flask development server
    # debug=True enables auto-reload and better error pages
    app.run(debug=True)
