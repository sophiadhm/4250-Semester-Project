# Calendar synchronization module for ICS (iCalendar) feed integration
# Fetches assignments from external calendar feeds and syncs them to database

import re
import requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from app.models import db, Assignment


def parse_ics_date(ics_date_str):
    """
    Parses various ICS date/time formats from calendar feeds.

    Supports:
        - DTSTART:20240620T235900Z (UTC with Z suffix)
        - DTSTART;TZID=America/New_York:20240620T235900 (timezone ID)
        - DTSTART;VALUE=DATE:20240620 (date only, no time)

    Returns:
        Tuple of (due_date_iso, due_time_hms):
        - due_date_iso: ISO format date string (YYYY-MM-DD)
        - due_time_hms: Time in HH:MM:SS format, or None for date-only
    """
    # Get the line and split on first colon
    line = ics_date_str.strip()
    if ":" not in line:
        raise ValueError("Invalid DTSTART line")

    prefix, raw = line.split(":", 1)
    raw = raw.strip()

    if not raw:
        raise ValueError("Empty DTSTART")

    def parse_compact_datetime(value):
        """Parse compact ICS datetime value with or without seconds."""
        compact = value.strip()
        if len(compact) == 15:
            return datetime.strptime(compact, "%Y%m%dT%H%M%S")
        if len(compact) == 13:
            return datetime.strptime(compact, "%Y%m%dT%H%M")
        raise ValueError(f"Invalid ICS datetime format: {value}")

    # Extract timezone if specified (e.g., TZID=America/New_York)
    tz = None
    if "TZID=" in prefix:
        tzid = prefix.split("TZID=", 1)[1].split(";", 1)[0]
        try:
            tz = ZoneInfo(tzid)
        except Exception:
            # If timezone is invalid, ignore it
            tz = None

    # Check if time component is included in the date string
    has_time = "T" in raw

    # If no time or VALUE=DATE is specified, treat as date-only
    if not has_time or "VALUE=DATE" in prefix:
        # Parse date-only format (YYYYMMDD)
        due_date = datetime.strptime(raw[:8], "%Y%m%d").date().isoformat()
        return due_date, None

    # Process date with time component
    parse_raw = raw
    source_has_explicit_offset = False

    # Convert Z (UTC) suffix to +00:00 format for parsing
    if parse_raw.endswith("Z"):
        parse_raw = parse_raw[:-1] + "+00:00"
        source_has_explicit_offset = True

    # Parse datetime with timezone offset if present
    if "+" in parse_raw[-6:] or "-" in parse_raw[-6:]:
        source_has_explicit_offset = True
        # datetime with timezone offset
        try:
            dt = datetime.fromisoformat(parse_raw)
        except Exception:
            # Fallback: parse without offset and assume UTC
            compact_no_offset = re.sub(r"[+-]\d{2}:?\d{2}$", "", parse_raw)
            dt = parse_compact_datetime(compact_no_offset).replace(tzinfo=timezone.utc)
    else:
        # No timezone offset in string
        dt = parse_compact_datetime(parse_raw)
        # Apply timezone if we extracted one earlier
        if tz:
            dt = dt.replace(tzinfo=tz)

    # Convert explicit UTC/offset times to local timezone for day display.
    # Keep TZID/floating times as-is so they don't drift by host timezone.
    if source_has_explicit_offset and dt.tzinfo is not None:
        dt = dt.astimezone()

    due_date = dt.date().isoformat()
    due_time = dt.time().strftime("%H:%M:%S")

    return due_date, due_time


def parse_course_id(title):
    """
    Extracts 4-digit course code from assignment title using regex.

    Examples:
        "CS 3050 - Assignment 1" -> "3050"
        "Software Engineering Project" -> "0000" (fallback)

    Returns:
        4-digit course code as string, or "0000" if not found
    """
    # Search for any 4-digit number in the title
    match = re.search(r"\b(\d{4})\b", title)
    if match:
        return match.group(1)
    # Return default if no code found
    return "0000"


def generate_course_color(course_code_or_name):
    """Generate a consistent hex color for a course based on its code/name.

    Same input always produces same color, so each course maintains
    consistent color across assignments.

    Args:
        course_code_or_name: Course code (e.g., "4250") or course name

    Returns:
        Hex color string like "#517664"
    """
    if not course_code_or_name:
        return "#517664"  # Default color

    # Create a consistent hash from the course identifier
    hash_val = sum(ord(c) for c in str(course_code_or_name))

    # Predefined palette of nice colors for courses
    colors = [
        "#517664",  # Sage green (default)
        "#FF6B6B",  # Coral red
        "#4ECDC4",  # Turquoise
        "#45B7D1",  # Sky blue
        "#FFA07A",  # Light salmon
        "#98D8C8",  # Mint
        "#F7DC6F",  # Golden
        "#BB8FCE",  # Purple
        "#85C1E2",  # Periwinkle
        "#F8B88B",  # Peach
    ]

    return colors[hash_val % len(colors)]


def extract_course_code_from_location(location):
    """
    Extracts the 4-digit course code from D2L LOCATION field.

    D2L format: "CSCI-4250-800 - Software Engineer I"
    Extracts: "4250"

    Args:
        location: LOCATION field value from ICS event

    Returns:
        4-digit course code as string, or "0000" if not found
    """
    if not location:
        return "0000"

    # D2L format: CoursePrefix-4digitCode-Section
    # Example: "CSCI-4250-800 - Software Engineer I"
    # Extract the first sequence of digits after a dash
    match = re.search(r"-(\d{4})-", location)
    if match:
        return match.group(1)

    # Fallback: just look for any 4-digit number
    match = re.search(r"\b(\d{4})\b", location)
    if match:
        return match.group(1)

    return "0000"


def parse_course(title):
    """
    Extracts the course label from an assignment title.

    Examples:
        "CS 3050 - Assignment 1" -> "CS 3050"
        "CSCI 4250: Project 2" -> "CSCI 4250"
        "Software Engineering - Final Exam" -> "Software Engineering"
    """
    # Look for a leading course or class segment before a separator.
    for sep in (" - ", ":", "|"):
        if sep in title:
            candidate = title.split(sep, 1)[0].strip()
            if candidate and candidate != title:
                return candidate

    # Fallback: if title contains a course code, return the code with any prefix.
    match = re.search(r"\b[A-Za-z]{2,}\s*\d{4}\b", title)
    if match:
        return match.group(0).strip()

    # If no course-like segment can be extracted, return None so UI can omit it.
    return None


def unfold_ics_lines(raw_lines):
    """Unfold ICS lines that continue on the next line with leading whitespace."""
    unfolded = []
    for line in raw_lines:
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line.lstrip()
        else:
            unfolded.append(line)
    return unfolded


def extract_assignment_type(lines, title):
    """Extract assignment type from ICS DESCRIPTION field.

    D2L typically includes activity type at the start of DESCRIPTION:
    - "Dropbox:" = submitted work
    - "Modules:" = learning module
    - "Quizzes:" = quiz/test
    - "Assignments:" = assignment
    - etc.
    """
    description_line = next(
        (line for line in lines if line.split(":", 1)[0].split(";", 1)[0] == "DESCRIPTION"),
        None,
    )
    if not description_line:
        return None

    if ":" not in description_line:
        return None
    _, desc_value = description_line.split(":", 1)
    desc_value = desc_value.strip()

    # Map common D2L type prefixes to readable names
    type_map = {
        "Dropbox": "Submission",
        "Modules": "Module",
        "Quizzes": "Quiz",
        "Assignments": "Assignment",
        "Assessments": "Assessment",
        "Discussions": "Discussion",
        "Surveys": "Survey",
    }

    for prefix, type_name in type_map.items():
        if desc_value.startswith(prefix + ":"):
            return type_name

    return None


def get_default_priority_for_type(assignment_type):
    """Get default priority level based on assignment type.

    Priority mapping:
    - High (3): Assignments, Assessments, Submissions
    - Medium (2): Quizzes, Surveys
    - Low (1): Modules, Discussions
    - None: Unknown types
    """
    if not assignment_type:
        return None

    high_priority = ["Assignment", "Assessment", "Submission"]
    medium_priority = ["Quiz", "Survey"]
    low_priority = ["Module", "Discussion"]

    if assignment_type in high_priority:
        return 3  # High
    elif assignment_type in medium_priority:
        return 2  # Medium
    elif assignment_type in low_priority:
        return 1  # Low

    return None  # Unknown type


def extract_course_from_event(lines, title):
    """Extract course info from ICS event fields.

    D2L feeds store course as: LOCATION:CourseCode-CourseSection - CourseName
    Example: LOCATION:CSCI-4250-800 - Software Engineer I
    """
    # Try LOCATION first (D2L standard format)
    location_line = next(
        (line for line in lines if line.split(":", 1)[0].split(";", 1)[0] == "LOCATION"),
        None,
    )
    if location_line:
        if ":" not in location_line:
            return None
        _, value = location_line.split(":", 1)
        value = value.strip().replace("\\n", " ")

        # Parse D2L format: "CSCI-4250-800 - Software Engineer I"
        if " - " in value:
            parts = value.split(" - ", 1)
            if len(parts) == 2:
                # Return the course name part (after the dash)
                return parts[1].strip()

    # Fallback to other fields if LOCATION didn't work
    for prefix in ("DESCRIPTION:", "CATEGORIES:", "COMMENT:"):
        line = next((line for line in lines if line.startswith(prefix)), None)
        if not line:
            continue
        if ":" not in line:
            continue
        _, value = line.split(":", 1)
        value = value.strip().replace("\\n", " ").strip()
        if not value or value == title:
            continue
        # Look for explicit course pattern
        match = re.search(r"\b(?:Course|Class|Subject)\s*:\s*(.+)", value, re.I)
        if match:
            return match.group(1).strip()

    return None


def sync_assignments(user):
    """
    Fetches assignments from user's ICS calendar feed and syncs to database.

    Process:
        1. Fetches ICS file from user.ics_url
        2. Parses VEVENT entries from calendar
        3. Updates existing assignments that changed
        4. Creates new assignments from calendar
        5. Deletes assignments no longer in calendar

    Args:
        user: User object with ics_url set
    """
    # Skip if user hasn't configured a calendar URL
    if not user.ics_url:
        return

    # Fetch ICS calendar file from URL
    try:
        response = requests.get(user.ics_url)
        # Raise exception if request failed
        response.raise_for_status()
    except Exception as e:
        # Log error and exit gracefully if fetch fails
        print("ICS fetch failed:", e)
        return

    # Get raw ICS file content
    ics_text = response.text
    # Split into individual event blocks (VEVENT entries)
    events = ics_text.split("BEGIN:VEVENT")[1:]

    # Track UIDs and titles of assignments synced in this update
    # Used later to identify deleted assignments
    seen_uids = set()
    seen_titles = set()

    # Process each event from calendar
    for event_text in events:
        # Split event into individual lines for parsing and unfold any folded ICS lines
        raw_lines = event_text.splitlines()
        lines = unfold_ics_lines(raw_lines)

        # Extract UID (unique identifier for this event)
        uid_line = next((line for line in lines if line.startswith("UID:")), None)
        uid = uid_line.replace("UID:", "").strip() if uid_line else None

        # Extract SUMMARY (assignment title/name)
        title_line = next((line for line in lines if line.startswith("SUMMARY:")), None)
        title = title_line.replace("SUMMARY:", "").strip() if title_line else "No Title"

        # Extract due date/time, preferring DUE when available.
        # D2L assignment feeds may include DUE that differs from DTSTART.
        dt_line = next((line for line in lines if line.startswith("DUE")), None)
        if not dt_line:
            dt_line = next((line for line in lines if line.startswith("DTSTART")), None)
        if not dt_line:
            dt_line = next((line for line in lines if line.startswith("DTEND")), None)
        if not dt_line:
            # No date info, skip this event
            continue

        # Parse the date/time string
        try:
            due_date, due_time = parse_ics_date(dt_line)
        except Exception:
            # Skip events with unparseable dates
            continue

        course = extract_course_from_event(lines, title)
        if not course:
            course = parse_course(title)
        if course == title:
            course = None

        # Extract course code - try LOCATION field first (D2L format), then fallback to title
        location_line = next(
            (line for line in lines if line.split(":", 1)[0].split(";", 1)[0] == "LOCATION"),
            None,
        )
        if location_line and ":" in location_line:
            _, location_value = location_line.split(":", 1)
            course_id = extract_course_code_from_location(location_value.strip())
        else:
            course_id = parse_course_id(title)

        # Extract assignment type from DESCRIPTION field
        assignment_type = extract_assignment_type(lines, title)

        # Check if assignment already exists in database
        existing = None
        # First try matching by UID (most reliable)
        if uid:
            existing = Assignment.query.filter_by(user_id=user.id, ics_uid=uid).first()
        # Fallback to matching by title
        if not existing:
            existing = Assignment.query.filter_by(user_id=user.id, name=title).first()

        # If assignment exists, update it with new info
        if existing:
            # Update due date if changed
            if existing.due_date != due_date:
                existing.due_date = due_date
            # Update due time if changed and provided
            if due_time and existing.due_time != due_time:
                existing.due_time = due_time

            # Update course info
            existing.course = course
            existing.course_id = course_id
            existing.assignment_type = assignment_type
            # Generate color for this course
            existing.color = generate_course_color(course_id)
            # Set default priority based on assignment type if not already set
            if existing.priority_level is None:
                existing.priority_level = get_default_priority_for_type(assignment_type)
            # Store UID for robust future matching
            existing.ics_uid = uid or existing.ics_uid
        else:
            # Create new assignment from calendar event
            default_priority = get_default_priority_for_type(assignment_type)
            assignment = Assignment(
                name=title,
                due_date=due_date,
                user_id=user.id,
                ics_uid=uid,
                course=course,
                course_id=course_id,
                due_time=due_time,
                assignment_type=assignment_type,
                priority_level=default_priority,  # Set based on assignment type
                points=None,  # Not provided by calendar
                color=generate_course_color(course_id)  # Assign consistent color per course
            )
            # Add new assignment to database session
            db.session.add(assignment)

        # Track this event so we know it wasn't deleted
        if uid:
            seen_uids.add(uid)
        else:
            seen_titles.add(title)

    # Delete assignments that are no longer in the calendar feed
    # This keeps the database in sync when assignments are removed from calendar
    existing_assignments = Assignment.query.filter_by(user_id=user.id).all()
    for assignment in existing_assignments:
        # Check if assignment still exists in calendar feed
        if assignment.ics_uid:
            # Check by UID if available
            if assignment.ics_uid not in seen_uids:
                # Assignment was deleted from calendar, remove from database
                db.session.delete(assignment)
        else:
            # Check by title if no UID
            if assignment.name not in seen_titles:
                # Assignment was deleted from calendar, remove from database
                db.session.delete(assignment)

    # Commit all changes (updates, inserts, deletes) to database
    db.session.commit()
