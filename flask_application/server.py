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
from flask_application.sync import sync_assignments

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
    from app.models import CourseColor, Assignment

    # Handle form submission (POST request)
    if request.method == "POST":
        # Update course colors
        for key, value in request.form.items():
            if key.startswith('color_'):
                course = key[len('color_'):]
                color = value
                course_color = CourseColor.query.filter_by(user_id=current_user.id, course=course).first()
                if course_color:
                    course_color.color = color
                else:
                    db.session.add(CourseColor(user_id=current_user.id, course=course, color=color))
                # Update all assignments for this course
                Assignment.query.filter_by(user_id=current_user.id, course=course).update({"color": color})
        # Update password and ICS URL as before
        new_password = request.form.get("password")
        ics_url = request.form.get("ics_url")
        if new_password:
            current_user.set_password(new_password)
        if ics_url:
            current_user.ics_url = ics_url
        db.session.commit()
        flash("Account updated!", "success")
        return redirect(url_for("account"))

    # Gather all courses for this user (from assignments and course colors)
    course_names = set([a.course for a in Assignment.query.filter_by(user_id=current_user.id).all() if a.course])
    course_colors = {c.course: c.color for c in CourseColor.query.filter_by(user_id=current_user.id).all()}
    courses = [(course, course_colors.get(course, "#517664")) for course in sorted(course_names)]
    print("[DEBUG] Course colors for account page:", courses)
    return render_template("account.html", courses=courses)

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
    from datetime import date
    # Query all assignments for current user, sorted by due date, only today or future
    today = date.today()
    assignments = Assignment.query.filter(
        Assignment.user_id == current_user.id,
        Assignment.due_date >= today
    ).order_by(Assignment.due_date).all()
    # Get course color mapping
    from app.models import CourseColor
    course_colors = {c.course: c.color for c in CourseColor.query.filter_by(user_id=current_user.id).all()}

    # Convert Assignment objects to dicts for JSON serialization in template
    def assignment_to_dict(a):
        color = course_colors.get(a.course, a.color or "#517664")
        return {
            "id": a.id,
            "name": a.name,
            "due_date": a.due_date,
            "due_time": a.due_time,
            "course": a.course,
            "course_id": a.course_id,
            "color": color,
            "priority_level": a.priority_level,
            "assignment_type": a.assignment_type,
            "points": a.points,
            "ics_uid": a.ics_uid,
        }
    assignments_dict = [assignment_to_dict(a) for a in assignments]
    return render_template('index.html', assignments=assignments_dict)


# CREATE NEW ASSIGNMENT - Adds a new assignment to the database
@app.route("/assignments/new", methods=["POST"])
@login_required  # Require user to be logged in
def new_assignment():
    # Build assignment data from form fields
    data = {
        "user_id": current_user.id,  # Set current user as owner
        "name": request.form.get("name"),  # Assignment name
        "course": request.form.get("course"),  # Course name
        "due_date": request.form.get("due_date"),  # Due date
        "priority_level": request.form.get("priority"),  # Priority level
        "course_id": "0000",  # Default course code
        "due_time": None,  # Not provided in this form
        "assignment_type": None,  # Not provided in this form
        "points": None,  # Not provided in this form
        "color": request.form.get("class_color") or "#517664"  # Course color from form
    }

    # Send POST request to FastAPI backend to create assignment
    requests.post("http://127.0.0.1:8000/assignments/", json=data)
    # Redirect to home page to show new assignment
    return redirect(url_for("index"))

# DELETE an assignment
@app.route("/assignments/<int:assignment_id>/delete", methods=["POST"])
@login_required
def delete_assignment(assignment_id):
    assignment = Assignment.query.filter_by(id=assignment_id, user_id=current_user.id).first()
    if not assignment:
        flash("Assignment not found.", "error")
        return redirect(url_for("index"))
    db.session.delete(assignment)
    db.session.commit()
    flash("Assignment deleted.", "success")
    return redirect(url_for("index"))

# EDIT an assignment
@app.route("/assignments/<int:assignment_id>/edit", methods=["POST"])
@login_required
def edit_assignment(assignment_id):
    assignment = Assignment.query.filter_by(id=assignment_id, user_id=current_user.id).first()
    if not assignment:
        flash("Assignment not found.", "error")
        return redirect(url_for("index"))
    assignment.name = request.form.get("name", assignment.name)
    assignment.course = request.form.get("course", assignment.course)
    assignment.due_date = request.form.get("due_date", assignment.due_date)
    assignment.priority_level = request.form.get("priority", assignment.priority_level)
    db.session.commit()
    flash("Assignment updated!", "success")
    return redirect(url_for("index"))

# ============================================================================
# CALENDAR INTEGRATION ROUTES
# ============================================================================

# CALENDAR PAGE - Displays assignments in calendar view and supports ICS sync
@app.route("/calendar/")
@login_required  # Require user to be logged in
def about():
    from datetime import datetime
    import re
    
    # If user has connected a calendar, sync latest assignments from it
    if current_user.ics_url:
        sync_assignments(current_user)

    # Query all assignments for current user, sorted by due date
    raw_assignments = Assignment.query.filter_by(user_id=current_user.id).order_by(Assignment.due_date).all()

    # Check for filter in query string (for server-side rendering, e.g. for non-JS clients)
    hide_available = (request.args.get('hide_available') == '1')

    def normalize_date(due_date_str):
        """Normalize date to ISO format YYYY-MM-DD"""
        if not due_date_str:
            return None
        due_date = due_date_str.strip()
        try:
            patterns = [
                ('%Y-%m-%d', 'YYYY-MM-DD'),
                ('%m/%d/%Y', 'MM/DD/YYYY'),
                ('%m-%d-%Y', 'MM-DD-YYYY'),
                ('%Y/%m/%d', 'YYYY/MM/DD'),
                ('%d/%m/%Y', 'DD/MM/YYYY'),
                ('%d-%m-%Y', 'DD-MM-YYYY'),
            ]
            for fmt, name in patterns:
                try:
                    dt = datetime.strptime(due_date, fmt)
                    return dt.strftime('%Y-%m-%d')
                except ValueError:
                    continue
            match = re.search(r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', due_date)
            if match:
                month, day, year = match.groups()
                dt = datetime(int(year), int(month), int(day))
                return dt.strftime('%Y-%m-%d')
            if re.match(r'^\d{4}-\d{2}-\d{2}$', due_date):
                return due_date
            print(f"Warning: Could not parse due_date '{due_date}' with any known format")
            return None
        except Exception as e:
            print(f"Error parsing due_date '{due_date}': {e}")
            return None

    # Use CourseColor for color lookup
    from app.models import CourseColor
    course_colors = {c.course: c.color for c in CourseColor.query.filter_by(user_id=current_user.id).all()}

    assignments = []
    for a in raw_assignments:
        if hide_available and a.name and 'available' in a.name.lower():
            continue
        normalized_date = normalize_date(a.due_date)
        if not normalized_date:
            continue
        color = course_colors.get(a.course, a.color or '#517664')
        assignments.append({
            'id': a.id,
            'name': a.name,
            'course': a.course,
            'course_id': a.course_id,
            'due_date': normalized_date,
            'due_time': a.due_time,
            'assignment_type': a.assignment_type,
            'priority_level': a.priority_level,
            'points': a.points,
            'ics_uid': a.ics_uid,
            'color': color,
        })
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
    raw_assignments = Assignment.query.filter_by(
        user_id=current_user.id
    ).order_by(Assignment.due_date).all()

    # Check for filter in query string (for server-side rendering, e.g. for non-JS clients)
    hide_available = (request.args.get('hide_available') == '1')

    assignments = []
    for a in raw_assignments:
        if hide_available and a.name and 'available' in a.name.lower():
            continue
        assignments.append(a)

    # Render template with assignments
    return render_template("assignments.html", assignments=assignments)


# APPLICATION ENTRY POINT
if __name__ == '__main__':
    # Run Flask development server
    # debug=True enables auto-reload and better error pages
    app.run(debug=True)
