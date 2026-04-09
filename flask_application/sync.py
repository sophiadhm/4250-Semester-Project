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

    # Convert Z (UTC) suffix to +00:00 format for parsing
    if parse_raw.endswith("Z"):
        parse_raw = parse_raw[:-1] + "+00:00"

    # Parse datetime with timezone offset if present
    if "+" in parse_raw[-6:] or "-" in parse_raw[-6:]:
        # datetime with timezone offset
        try:
            dt = datetime.fromisoformat(parse_raw)
        except Exception:
            # Fallback: parse without offset and assume UTC
            dt = datetime.strptime(parse_raw[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    else:
        # No timezone offset in string
        dt = datetime.strptime(parse_raw[:15], "%Y%m%dT%H%M%S")
        # Apply timezone if we extracted one earlier
        if tz:
            dt = dt.replace(tzinfo=tz)
        else:
            # Default to UTC if no timezone specified
            dt = dt.replace(tzinfo=timezone.utc)

    # Convert to local timezone to avoid date shift issues
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local_dt = dt.astimezone()  # Convert to local timezone for user-facing day

    # Extract date and time in local timezone
    due_date = local_dt.date().isoformat()
    due_time = local_dt.time().strftime("%H:%M:%S")

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
        # Split event into individual lines for parsing
        lines = event_text.splitlines()

        # Extract UID (unique identifier for this event)
        uid_line = next((line for line in lines if line.startswith("UID:")), None)
        uid = uid_line.replace("UID:", "").strip() if uid_line else None

        # Extract SUMMARY (assignment title/name)
        title_line = next((line for line in lines if line.startswith("SUMMARY:")), None)
        title = title_line.replace("SUMMARY:", "").strip() if title_line else "No Title"

        # Extract start date/time (DTSTART or DTEND as fallback)
        dt_line = next((line for line in lines if line.startswith("DTSTART")), None)
        if not dt_line:
            # Try DTEND if DTSTART not found
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

        # Use full title as course name
        course = title
        # Extract course code from title
        course_id = parse_course_id(title)

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
            # Store UID for robust future matching
            existing.ics_uid = uid or existing.ics_uid
        else:
            # Create new assignment from calendar event
            assignment = Assignment(
                name=title,
                due_date=due_date,
                user_id=user.id,
                ics_uid=uid,
                course=course,
                course_id=course_id,
                due_time=due_time,
                assignment_type=None,  # Not provided by calendar
                priority_level=None,  # Not provided by calendar
                points=None  # Not provided by calendar
            )
            # Add new assignment to database session
            db.session.add(assignment)

        # Track this event so we know it wasn't deleted
        if uid:
            seen_uids.add(uid)
        else:
            seen_titles.add(title)

        # DEBUG: show parsed assignment data and where it maps
        print(f"[sync] user={user.username} title={title!r} uid={uid!r} due_date={due_date} due_time={due_time} course_id={course_id}")

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
