# SQLAlchemy ORM model for the Assignment database table
# Used by FastAPI backend to interact with assignments in the database

from sqlalchemy import Column, Integer, String, Float
from app.database import Base

class Assignment(Base):
    """
    Database model representing an assignment entry.
    Maps to the 'assignments' table in the SQLite database.
    """
    __tablename__ = "assignments"

    # Primary key - unique identifier for each assignment
    id = Column(Integer, primary_key=True, index=True)

    # Foreign key to users table - identifies which user owns this assignment
    user_id = Column(Integer, nullable=True)

    # Unique identifier from ICS calendar feed (for sync tracking)
    # Indexed for fast lookups during calendar synchronization
    ics_uid = Column(String(255), nullable=True, index=True)

    # Course code (4 digit number like "3050" or "SYNC" for synced items)
    # Defaults to "SYNC" for calendar-synced assignments
    course_id = Column(String(4), nullable=True, default="SYNC")

    # Assignment name/title - indexed for searching
    name = Column(String, index=True)

    # Full course name (e.g., "Software Engineering")
    course = Column(String)

    # Due date in ISO format (YYYY-MM-DD)
    due_date = Column(String)

    # Due time in HH:MM:SS format (optional)
    due_time = Column(String)

    # Type of assignment (e.g., "homework", "exam", "project")
    assignment_type = Column(String)

    # Priority level (numerical scale, e.g., 1-5)
    priority_level = Column(Integer)

    # Point value for this assignment
    points = Column(Float)
