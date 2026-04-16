
# Flask-SQLAlchemy ORM models for the Flask web application
# Defines User and Assignment database tables and relationships
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

# Initialize SQLAlchemy database instance (will be attached to Flask app in server.py)
db = SQLAlchemy()

# --- CourseColor model for user course color preferences ---
# from sqlalchemy.orm import relationship

class CourseColor(db.Model):
    __tablename__ = "course_colors"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    course = db.Column(db.String, nullable=False)
    color = db.Column(db.String(7), nullable=False, default="#517664")
    __table_args__ = (db.UniqueConstraint('user_id', 'course', name='_user_course_uc'),)

class User(UserMixin, db.Model):
    """
    User account model for authentication and account management.
    Inherits from UserMixin to integrate with Flask-Login.
    """
    __tablename__ = "users"

    # Primary key - unique user identifier
    id = db.Column(db.Integer, primary_key=True)

    # Username - must be unique across all users
    username = db.Column(db.String(150), unique=True, nullable=False)

    # Password hash - stores hashed password for security
    password_hash = db.Column(db.String(150), nullable=False)

    # Admin flag - determines if user has administrative privileges
    is_admin = db.Column(db.Boolean, default=False)

    # ICS calendar URL - URL to external calendar feed for syncing assignments
    ics_url = db.Column(db.String(500))

    def set_password(self, password):
        """
        Hashes the provided password and stores it in password_hash.
        Use this when creating new users or changing passwords.

        Args:
            password: Plain text password to hash
        """
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """
        Verifies if provided password matches stored hash.
        Use this during login to authenticate users.

        Args:
            password: Plain text password to verify

        Returns:
            True if password matches, False otherwise
        """
        return check_password_hash(self.password_hash, password)


class Assignment(db.Model):
    """
    Assignment model for storing course assignments and tasks.
    Owned by a User (via user_id foreign key).
    """
    __tablename__ = "assignments"

    # Primary key - unique assignment identifier
    id = db.Column(db.Integer, primary_key=True, index=True)

    # Foreign key to users table - identifies which user owns this assignment
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # Unique identifier from ICS calendar feed (for tracking synced items)
    # Indexed for fast lookups during calendar synchronization
    ics_uid = db.Column(db.String(255), nullable=True, index=True)

    # Course code (4 digit number like "3050" or "SYNC" for synced items)
    # Defaults to "SYNC" for calendar-synced assignments
    course_id = db.Column(db.String(4), nullable=True, default="SYNC")

    # Assignment name/title - indexed for searching
    name = db.Column(db.String, index=True)

    # Full course name (e.g., "Software Engineering", "CS 3050")
    course = db.Column(db.String)

    # Due date in ISO format (YYYY-MM-DD)
    due_date = db.Column(db.String)

    # Due time in HH:MM:SS format (optional field)
    due_time = db.Column(db.String)

    # Type of assignment (e.g., "homework", "exam", "project", "quiz")
    assignment_type = db.Column(db.String)

    # Priority level (numerical scale, typically 1-5 for user prioritization)
    priority_level = db.Column(db.Integer)

    # Point value for this assignment (for grading calculations)
    points = db.Column(db.Float)

    # Course color for calendar/UI display (hex color code like #517664)
    color = db.Column(db.String(7), nullable=True, default="#517664")
