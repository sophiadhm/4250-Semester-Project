# Flask web application for assignment management
# Provides web UI for user authentication, assignment management, and calendar integration
import sys
import os

# Automatically find the project root (the folder containing both 'app' and 'flask_application')
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Add it to Python's module search path so we can import from 'app' package
if project_root not in sys.path:
    sys.path.append(project_root)


from flask import Flask, render_template, request, flash, redirect, url_for, jsonify
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from app.models import db, User, Assignment, CourseColor, NotificationLog, PushSubscription
from sqlalchemy import text
from flask_application.sync import sync_assignments
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import threading
import time
import json
import base64

try:
    from plyer import notification as plyer_notification
except Exception:
    plyer_notification = None

try:
    from pywebpush import webpush, WebPushException
except Exception:
    webpush = None
    WebPushException = Exception

try:
    from py_vapid import Vapid
    from cryptography.hazmat.primitives import serialization
except Exception:
    Vapid = None
    serialization = None

# Initialize Flask application
app = Flask(__name__)
# Secret key for session management and CSRF protection
app.secret_key = 'key'  # TODO: Use environment variable in production

VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
VAPID_PRIVATE_KEY_PATH = os.environ.get("VAPID_PRIVATE_KEY_PATH", "").strip()
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com").strip()
APP_TIMEZONE_NAME = os.environ.get("APP_TIMEZONE", "America/New_York").strip() or "America/New_York"

try:
    APP_TIMEZONE = ZoneInfo(APP_TIMEZONE_NAME)
except Exception:
    APP_TIMEZONE = ZoneInfo("UTC")

# FastAPI backend server URL for making requests to assignment API
URL = 'http://127.0.0.1:8000'


# DATABASE CONFIGURATION
# Get project root directory for locating database file
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def _public_vapid_key_from_private_pem(private_pem):
    if not private_pem or Vapid is None or serialization is None:
        return ""
    try:
        vapid_obj = Vapid.from_string(private_pem)
        public_raw = vapid_obj.public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
        return base64.urlsafe_b64encode(public_raw).decode().rstrip("=")
    except Exception as exc:
        print(f"[WARN] Failed to derive VAPID public key from private key: {exc}")
        return ""


def _init_vapid_keys():
    global VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_PRIVATE_KEY_PATH

    if webpush is None:
        return

    configured_private = ""
    if VAPID_PRIVATE_KEY:
        configured_private = VAPID_PRIVATE_KEY.replace("\\n", "\n")
    elif VAPID_PRIVATE_KEY_PATH and os.path.exists(VAPID_PRIVATE_KEY_PATH):
        try:
            with open(VAPID_PRIVATE_KEY_PATH, "r", encoding="utf-8") as file_obj:
                configured_private = file_obj.read().strip()
        except Exception as exc:
            print(f"[WARN] Failed to read VAPID private key file: {exc}")

    if VAPID_PUBLIC_KEY and configured_private:
        VAPID_PRIVATE_KEY = configured_private
        return

    if configured_private and not VAPID_PUBLIC_KEY:
        derived_public = _public_vapid_key_from_private_pem(configured_private)
        if derived_public:
            VAPID_PRIVATE_KEY = configured_private
            VAPID_PUBLIC_KEY = derived_public
            return

    if Vapid is None or serialization is None:
        print("[WARN] Web push keys are missing and py_vapid is unavailable; push notifications are disabled.")
        return

    try:
        instance_dir = os.path.join(BASE_DIR, "instance")
        auto_private_path = os.path.join(instance_dir, "vapid_private.pem")

        auto_private = ""
        auto_public = ""

        if os.path.exists(auto_private_path):
            with open(auto_private_path, "r", encoding="utf-8") as file_obj:
                auto_private = file_obj.read().strip()
            auto_public = _public_vapid_key_from_private_pem(auto_private)
        else:
            vapid_obj = Vapid()
            vapid_obj.generate_keys()
            auto_private = vapid_obj.private_pem().decode("utf-8").strip()
            public_raw = vapid_obj.public_key.public_bytes(
                encoding=serialization.Encoding.X962,
                format=serialization.PublicFormat.UncompressedPoint,
            )
            auto_public = base64.urlsafe_b64encode(public_raw).decode().rstrip("=")

            # Best-effort persistence; if this fails (read-only filesystem),
            # keep keys in memory so push still works for current process.
            try:
                os.makedirs(instance_dir, exist_ok=True)
                with open(auto_private_path, "w", encoding="utf-8") as file_obj:
                    file_obj.write(auto_private)
            except Exception as exc:
                print(f"[WARN] Could not persist VAPID private key file; using in-memory key: {exc}")

        if auto_private and auto_public:
            VAPID_PRIVATE_KEY = auto_private
            VAPID_PUBLIC_KEY = auto_public
            if not VAPID_PRIVATE_KEY_PATH and os.path.exists(auto_private_path):
                VAPID_PRIVATE_KEY_PATH = auto_private_path
            print("[INFO] Web push keys ready.")
    except Exception as exc:
        print(f"[WARN] Could not initialize VAPID keys automatically: {exc}")


def _web_push_status():
    private_key = _get_vapid_private_key()
    status = {
        "webpush_imported": webpush is not None,
        "py_vapid_imported": Vapid is not None and serialization is not None,
        "public_key_loaded": bool(VAPID_PUBLIC_KEY),
        "private_key_loaded": bool(private_key),
        "enabled": False,
        "reason": "",
    }

    if not status["webpush_imported"]:
        status["reason"] = "pywebpush import failed"
    elif not status["py_vapid_imported"] and not (status["public_key_loaded"] and status["private_key_loaded"]):
        status["reason"] = "py_vapid/cryptography unavailable and no preconfigured keys"
    elif not status["public_key_loaded"]:
        status["reason"] = "VAPID public key missing"
    elif not status["private_key_loaded"]:
        status["reason"] = "VAPID private key missing"
    else:
        status["enabled"] = True

    return status


_init_vapid_keys()


def _now_local():
    return datetime.now(APP_TIMEZONE)
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

    if "event_kind" not in assignment_col_names:
        db.session.execute(text("ALTER TABLE assignments ADD COLUMN event_kind VARCHAR(20) DEFAULT 'due'"))
        db.session.commit()

    user_cols = db.session.execute(text("PRAGMA table_info(users)")).fetchall()
    user_col_names = {col[1] for col in user_cols}

    if "notify_browser_enabled" not in user_col_names:
        db.session.execute(text("ALTER TABLE users ADD COLUMN notify_browser_enabled BOOLEAN DEFAULT 1"))
        db.session.commit()

    if "notify_minutes_before" not in user_col_names:
        db.session.execute(text("ALTER TABLE users ADD COLUMN notify_minutes_before INTEGER DEFAULT 60"))
        db.session.commit()

# Setup Flask-Login for user authentication
login_manager = LoginManager(app)
# Redirect unauthenticated users to login page
login_manager.login_view = 'login'
# Set flash message category for login messages
login_manager.login_message_category = 'error'


def _is_available_event(assignment):
    if assignment.event_kind == "available":
        return True
    name = (assignment.name or "").lower()
    return "available" in name or "opens" in name


def _assignment_due_datetime(assignment):
    if not assignment.due_date:
        return None
    try:
        due_day = datetime.strptime(str(assignment.due_date), "%Y-%m-%d").date()
    except ValueError:
        return None

    due_time_value = assignment.due_time or "23:59:00"
    try:
        due_time_obj = datetime.strptime(due_time_value, "%H:%M:%S").time()
    except ValueError:
        try:
            due_time_obj = datetime.strptime(due_time_value, "%H:%M").time()
        except ValueError:
            due_time_obj = datetime.strptime("23:59:00", "%H:%M:%S").time()

    return datetime.combine(due_day, due_time_obj)


def _normalize_due_date_to_date(due_date_value):
    if due_date_value is None:
        return None

    raw_value = str(due_date_value).strip()
    if not raw_value:
        return None

    patterns = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%Y/%m/%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
    ]

    for pattern in patterns:
        try:
            return datetime.strptime(raw_value, pattern).date()
        except ValueError:
            continue

    if len(raw_value) >= 10 and raw_value[4] == "-" and raw_value[7] == "-":
        try:
            return datetime.strptime(raw_value[:10], "%Y-%m-%d").date()
        except ValueError:
            return None

    return None


def _send_windows_notification(title, body):
    if os.name != "nt" or plyer_notification is None:
        return False

    try:
        truncated_body = (body or "")[:240]
        plyer_notification.notify(
            title=title or "Assignment Reminder",
            message=truncated_body,
            timeout=10,
            app_name="Calendrier",
        )
        return True
    except Exception as exc:
        print(f"[WARN] Windows notification failed: {exc}")
        return False


def _web_push_enabled():
    return _web_push_status()["enabled"]


def _get_vapid_private_key():
    if VAPID_PRIVATE_KEY:
        return VAPID_PRIVATE_KEY.replace("\\n", "\n")
    if VAPID_PRIVATE_KEY_PATH and os.path.exists(VAPID_PRIVATE_KEY_PATH):
        try:
            with open(VAPID_PRIVATE_KEY_PATH, "r", encoding="utf-8") as file_obj:
                return file_obj.read().strip()
        except Exception as exc:
            print(f"[WARN] Failed to read VAPID private key file: {exc}")
    return ""


def _send_web_push_to_user(user_id, title, body):
    if not _web_push_enabled():
        return 0

    subscriptions = PushSubscription.query.filter_by(user_id=user_id).all()
    if not subscriptions:
        return 0

    payload = json.dumps({
        "title": title,
        "body": body,
        "url": "/",
        "tag": "daily-assignments",
    })
    vapid_private_key = _get_vapid_private_key()

    sent_count = 0
    stale_ids = []

    for sub in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {
                        "p256dh": sub.p256dh,
                        "auth": sub.auth,
                    },
                },
                data=payload,
                vapid_private_key=vapid_private_key,
                vapid_claims={"sub": VAPID_SUBJECT},
            )
            sent_count += 1
        except WebPushException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code in (404, 410):
                stale_ids.append(sub.id)
            else:
                print(f"[WARN] Web push send failed for user {user_id}: {exc}")
        except Exception as exc:
            print(f"[WARN] Web push send failed for user {user_id}: {exc}")

    if stale_ids:
        PushSubscription.query.filter(PushSubscription.id.in_(stale_ids)).delete(synchronize_session=False)
        db.session.commit()

    return sent_count


def _build_daily_summary_for_user(user, now, ignore_sent_log=False, ignore_user_pref=False):
    if (not ignore_user_pref) and (not user.notify_browser_enabled):
        return None, None

    today_start = datetime.combine(now.date(), datetime.min.time())
    tomorrow_start = today_start + timedelta(days=1)

    if not ignore_sent_log:
        existing_daily = NotificationLog.query.filter(
            NotificationLog.user_id == user.id,
            NotificationLog.channel == "daily",
            NotificationLog.sent_at >= today_start,
            NotificationLog.sent_at < tomorrow_start,
        ).first()
        if existing_daily:
            return None, None

    assignments_due_today = []
    assignments = Assignment.query.filter(
        Assignment.user_id == user.id,
        Assignment.due_date.isnot(None)
    ).all()

    for assignment in assignments:
        if _is_available_event(assignment):
            continue
        due_date = _normalize_due_date_to_date(assignment.due_date)
        if not due_date:
            continue
        if due_date == now.date():
            assignments_due_today.append(assignment)

    if not assignments_due_today:
        return None, None

    assignments_due_today.sort(key=lambda a: (a.course or "Uncategorized", a.name or ""))
    count = len(assignments_due_today)
    assignment_list = "\n".join([
        f"• {a.name} ({a.course or 'No course'})"
        for a in assignments_due_today
    ])

    notification = {
        "title": f"You have {count} assignment{'s' if count != 1 else ''} due today",
        "body": assignment_list,
        "assignments": [{
            "assignment_id": a.id,
            "title": a.name,
            "course": a.course,
        } for a in assignments_due_today]
    }
    return notification, assignments_due_today[0].id


def _record_daily_notification_sent(user_id, assignment_id, now):
    existing_daily_key = NotificationLog.query.filter_by(
        user_id=user_id,
        assignment_id=assignment_id,
        channel="daily",
    ).first()

    if existing_daily_key:
        existing_daily_key.sent_at = now
    else:
        db.session.add(NotificationLog(
            user_id=user_id,
            assignment_id=assignment_id,
            channel="daily",
            sent_at=now,
        ))

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        print(f"[WARN] Failed to persist daily notification log for user {user_id}: {exc}")


def _sync_all_users():
    """Background job to sync assignments from all users' ICS feeds every hour."""
    users = User.query.all()
    for user in users:
        if user.ics_url:
            try:
                sync_assignments(user)
            except Exception as e:
                print(f"[WARN] Auto-sync failed for user {user.id}: {e}")


def _hourly_ics_sync():
    while True:
        try:
            with app.app_context():
                users_with_ics = User.query.filter(User.ics_url.isnot(None)).all()
                for user in users_with_ics:
                    sync_assignments(user)
                    now_local = _now_local()
                    notification, assignment_id = _build_daily_summary_for_user(user, now_local)
                    if notification and assignment_id:
                        _send_web_push_to_user(user.id, notification["title"], notification["body"])
                        _record_daily_notification_sent(user.id, assignment_id, now_local)
                print(f"[INFO] Hourly ICS sync complete for {len(users_with_ics)} users")
        except Exception as exc:
            print(f"[WARN] Hourly ICS sync failed: {exc}")
        time.sleep(3600)


def _queue_due_notifications():
    """Background worker for queuing notifications. Disabled in browser-only mode."""
    pass


def _start_background_workers_once():
    if app.config.get("TESTING"):
        return
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return
    if getattr(app, "_background_workers_started", False):
        return
    sync_worker = threading.Thread(target=_hourly_ics_sync, daemon=True)
    sync_worker.start()
    app._background_workers_started = True


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
        # Update password and ICS URL
        new_password = request.form.get("new_password") or request.form.get("password")
        ics_url = request.form.get("ics_url")
        notify_browser_enabled = request.form.get("notify_browser_enabled") == "on"
        notify_hours_before = request.form.get("notify_hours_before")
        if new_password:
            current_user.set_password(new_password)
        if ics_url:
            current_user.ics_url = ics_url

        if "notify_browser_enabled" in request.form or "notify_hours_before" in request.form or "notify_minutes_before" in request.form:
            current_user.notify_browser_enabled = notify_browser_enabled
            try:
                raw_hours = notify_hours_before if notify_hours_before is not None else request.form.get("notify_minutes_before")
                if raw_hours is None or str(raw_hours).strip() == "":
                    minutes_int = 60
                elif "notify_hours_before" in request.form:
                    hours_float = float(raw_hours)
                    minutes_int = int(hours_float * 60)
                else:
                    minutes_int = int(raw_hours)
                current_user.notify_minutes_before = max(0, minutes_int)
            except ValueError:
                current_user.notify_minutes_before = 60

        db.session.commit()
        flash("Account updated!", "success")
        return redirect(url_for("account"))

    # Gather all courses for this user (from assignments and course colors)
    course_names = set([a.course for a in Assignment.query.filter_by(user_id=current_user.id).all() if a.course])
    course_colors = {c.course: c.color for c in CourseColor.query.filter_by(user_id=current_user.id).all()}
    courses = [(course, course_colors.get(course, "#517664")) for course in sorted(course_names)]
    notify_hours_before = round((current_user.notify_minutes_before or 60) / 60, 2)
    print("[DEBUG] Course colors for account page:", courses)
    return render_template(
        "account.html",
        courses=courses,
        notify_hours_before=notify_hours_before,
    )


@app.context_processor
def inject_push_config():
    return {
        "web_push_public_key": VAPID_PUBLIC_KEY if _web_push_enabled() else "",
    }


@app.route("/api/push/subscribe", methods=["POST"])
@login_required
def push_subscribe():
    if not _web_push_enabled():
        return jsonify({"ok": False, "error": "Web push is not configured on this server."}), 503

    data = request.get_json(silent=True) or {}
    endpoint = data.get("endpoint")
    keys = data.get("keys") or {}
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")

    if not endpoint or not p256dh or not auth:
        return jsonify({"ok": False, "error": "Invalid push subscription payload."}), 400

    subscription = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if subscription:
        subscription.user_id = current_user.id
        subscription.p256dh = p256dh
        subscription.auth = auth
    else:
        db.session.add(PushSubscription(
            user_id=current_user.id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
        ))

    db.session.commit()
    return jsonify({"ok": True})

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
    # Query all assignments for current user and normalize/filter in Python
    today_iso = _now_local().date().isoformat()
    raw_assignments = Assignment.query.filter(
        Assignment.user_id == current_user.id
    ).all()

    def normalize_date(due_date):
        if due_date is None:
            return None
        due_date_str = str(due_date).strip()
        if not due_date_str:
            return None
        try:
            patterns = [
                '%Y-%m-%d',
                '%m/%d/%Y',
                '%m-%d-%Y',
                '%Y/%m/%d',
                '%d/%m/%Y',
                '%d-%m-%Y',
            ]
            for fmt in patterns:
                try:
                    return datetime.strptime(due_date_str, fmt).strftime('%Y-%m-%d')
                except ValueError:
                    continue
            if len(due_date_str) >= 10 and due_date_str[4] == '-' and due_date_str[7] == '-':
                return due_date_str[:10]
            return None
        except Exception:
            return None

    assignments = []
    for assignment in raw_assignments:
        normalized_due_date = normalize_date(assignment.due_date)
        if not normalized_due_date:
            continue
        if normalized_due_date < today_iso:
            continue
        assignment._normalized_due_date = normalized_due_date
        assignments.append(assignment)

    assignments.sort(key=lambda a: ((a._normalized_due_date or ''), (a.due_time or '')))
    # Get course color mapping
    from app.models import CourseColor
    course_colors = {c.course: c.color for c in CourseColor.query.filter_by(user_id=current_user.id).all()}

    # Convert Assignment objects to dicts for JSON serialization in template
    def assignment_to_dict(a):
        color = course_colors.get(a.course, a.color or "#517664")
        return {
            "id": a.id,
            "name": a.name,
            "due_date": getattr(a, "_normalized_due_date", a.due_date),
            "due_time": a.due_time,
            "course": a.course,
            "course_id": a.course_id,
            "color": color,
            "priority_level": a.priority_level,
            "assignment_type": a.assignment_type,
            "points": a.points,
            "ics_uid": a.ics_uid,
            "event_kind": a.event_kind,
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
        "color": request.form.get("class_color") or "#517664",  # Course color from form
        "event_kind": "due"
    }
    course = data["course"]
    color = data["color"]

    if course:
        existing = CourseColor.query.filter_by(
            user_id=current_user.id,
            course=course
        ).first()

        if existing:
            existing.color = color
        else:
            db.session.add(CourseColor(
                user_id=current_user.id,
                course=course,
                color=color
            ))

        db.session.commit()

    # Create assignment directly in the database
    new = Assignment(
        user_id=data["user_id"],
        name=data["name"],
        course=data["course"],
        due_date=data["due_date"],
        priority_level=data["priority_level"],
        course_id=data["course_id"],
        due_time=data["due_time"],
        assignment_type=data["assignment_type"],
        points=data["points"],
        color=data["color"],
        event_kind=data["event_kind"],
    )
    db.session.add(new)
    db.session.commit()
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
        if hide_available and _is_available_event(a):
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
            'event_kind': a.event_kind,
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
        if hide_available and _is_available_event(a):
            continue
        assignments.append(a)

    # Render template with assignments
    return render_template("assignments.html", assignments=assignments)


# APPLICATION ENTRY POINT
@app.route("/api/notifications/pending")
@login_required
def pending_notifications():
    now_local = _now_local()
    notification, assignment_id = _build_daily_summary_for_user(current_user, now_local)
    if not notification or not assignment_id:
        return jsonify([])

    _send_windows_notification(notification["title"], notification["body"])
    _send_web_push_to_user(current_user.id, notification["title"], notification["body"])
    _record_daily_notification_sent(current_user.id, assignment_id, now_local)
    return jsonify([notification])


@app.route("/api/notifications/test", methods=["POST"])
@login_required
def test_notifications():
    notification, _ = _build_daily_summary_for_user(
        current_user,
        _now_local(),
        ignore_sent_log=True,
        ignore_user_pref=True,
    )

    if notification:
        test_title = notification.get("title") or "Assignments due today"
        test_body = notification.get("body") or ""
    else:
        test_title = "You have 0 assignments due today"
        test_body = "No assignments due today."

    windows_sent = _send_windows_notification(test_title, test_body)
    push_status = _web_push_status()
    web_push_sent_count = _send_web_push_to_user(current_user.id, test_title, test_body)
    subscription_count = PushSubscription.query.filter_by(user_id=current_user.id).count()

    return jsonify({
        "ok": True,
        "title": test_title,
        "body": test_body,
        "is_real_today_summary": bool(notification),
        "assignment_count_today": len(notification.get("assignments", [])) if notification else 0,
        "channels": {
            "windows_local_fallback_sent": windows_sent,
            "web_push_enabled": push_status["enabled"],
            "web_push_sent_count": web_push_sent_count,
            "push_subscription_count": subscription_count,
            "web_push_reason": push_status["reason"],
            "web_push_debug": {
                "webpush_imported": push_status["webpush_imported"],
                "py_vapid_imported": push_status["py_vapid_imported"],
                "public_key_loaded": push_status["public_key_loaded"],
                "private_key_loaded": push_status["private_key_loaded"],
            },
        },
    })


_start_background_workers_once()

if __name__ == '__main__':
    # Run Flask development server
    # debug=True enables auto-reload and better error pages
    app.run(debug=True)
