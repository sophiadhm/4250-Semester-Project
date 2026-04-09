# Pydantic models for request/response validation in FastAPI
# These schemas validate incoming data and serialize database objects to JSON

from pydantic import BaseModel, StringConstraints
from typing import Annotated

# Custom type: Course ID must be exactly 4 digits
CourseID = Annotated[
    str,
    StringConstraints(pattern=r'^\d{4}$')
]

# Base schema with common assignment fields used across create/update operations
class AssignmentBase(BaseModel):
    # User that owns this assignment
    user_id: int
    # Assignment name/title
    name: str
    # Full course name
    course: str
    # 4-digit course code (defaults to no code)
    course_id: str = "0000"
    # Due date in ISO format (YYYY-MM-DD)
    due_date: str
    # Due time in HH:MM:SS format (optional)
    due_time: str | None = None
    # Type of assignment (optional)
    assignment_type: str | None = None
    # Priority level 1-5 or similar scale (optional)
    priority_level: int | None = None
    # Point value for grading (optional)
    points: float | None = None


# Request schema for POST /assignments/ (creating new assignment)
class AssignmentCreate(BaseModel):
    # User that owns this assignment
    user_id: int
    # Assignment name/title
    name: str
    # Full course name
    course: str
    # 4-digit course code (defaults to no code)
    course_id: str = "0000"
    # Due date in ISO format - required field
    due_date: str
    # Optional fields default to None if not provided in request
    due_time: str | None = None  # Due time in HH:MM:SS format
    assignment_type: str | None = None  # Type of assignment
    priority_level: int | None = None  # Priority level
    points: float | None = None  # Point value


# Request schema for PUT /assignments/{id} (updating existing assignment)
# All fields are optional - only provided fields will be updated (partial updates)
class AssignmentUpdate(BaseModel):
    # User that owns this assignment (optional to update)
    user_id: int | None = None
    # Assignment name/title (optional to update)
    name: str | None = None
    # Full course name (optional to update)
    course: str | None = None
    # 4-digit course code - must match strict format if provided (optional to update)
    course_id: CourseID | None = None
    # Due date in ISO format (optional to update)
    due_date: str | None = None
    # Due time in HH:MM:SS format (optional to update)
    due_time: str | None = None
    # Type of assignment (optional to update)
    assignment_type: str | None = None
    # Priority level (optional to update)
    priority_level: int | None = None
    # Point value (optional to update)
    points: float | None = None


# Response schema for returning assignments from API endpoints
# Includes all base fields plus the auto-generated id from database
class AssignmentResponse(AssignmentBase):
    # Auto-generated primary key from database
    id: int

    class Config:
        # Allows SQLAlchemy ORM objects to be converted to Pydantic models
        from_attributes = True
