# sync.py
import re
import requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from app.models import db, Assignment


def parse_ics_date(ics_date_str):
    # Support lines like:
    # DTSTART:20240620T235900Z
    # DTSTART;TZID=America/New_York:20240620T235900
    # DTSTART;VALUE=DATE:20240620

    line = ics_date_str.strip()
    if ":" not in line:
        raise ValueError("Invalid DTSTART line")

    prefix, raw = line.split(":", 1)
    raw = raw.strip()

    if not raw:
        raise ValueError("Empty DTSTART")

    tz = None
    if "TZID=" in prefix:
        tzid = prefix.split("TZID=", 1)[1].split(";", 1)[0]
        try:
            tz = ZoneInfo(tzid)
        except Exception:
            tz = None

    has_time = "T" in raw

    if not has_time or "VALUE=DATE" in prefix:
        due_date = datetime.strptime(raw[:8], "%Y%m%d").date().isoformat()
        return due_date, None

    parse_raw = raw

    if parse_raw.endswith("Z"):
        parse_raw = parse_raw[:-1] + "+00:00"

    if "+" in parse_raw[-6:] or "-" in parse_raw[-6:]:
        # datetime with timezone offset
        try:
            dt = datetime.fromisoformat(parse_raw)
        except Exception:
            dt = datetime.strptime(parse_raw[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    else:
        dt = datetime.strptime(parse_raw[:15], "%Y%m%dT%H%M%S")
        if tz:
            dt = dt.replace(tzinfo=tz)
        else:
            dt = dt.replace(tzinfo=timezone.utc)

    # convert UTC/timezone-aware to local timezone for user-facing day (avoids date shift issues)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local_dt = dt.astimezone()  # local timezone

    due_date = local_dt.date().isoformat()
    due_time = local_dt.time().strftime("%H:%M:%S")

    return due_date, due_time


def parse_course_id(title):
    match = re.search(r"\b(\d{4})\b", title)
    if match:
        return match.group(1)
    return "0000"  # fallback


def sync_assignments(user):
    if not user.ics_url:
        return

    try:
        response = requests.get(user.ics_url)
        response.raise_for_status()
    except Exception as e:
        print("ICS fetch failed:", e)
        return

    ics_text = response.text
    events = ics_text.split("BEGIN:VEVENT")[1:]

    seen_uids = set()
    seen_titles = set()

    for event_text in events:
        lines = event_text.splitlines()

        # --- UID ---
        uid_line = next((line for line in lines if line.startswith("UID:")), None)
        uid = uid_line.replace("UID:", "").strip() if uid_line else None

        # --- TITLE ---
        title_line = next((line for line in lines if line.startswith("SUMMARY:")), None)
        title = title_line.replace("SUMMARY:", "").strip() if title_line else "No Title"

        # --- DATE ---
        dt_line = next((line for line in lines if line.startswith("DTSTART")), None)
        if not dt_line:
            dt_line = next((line for line in lines if line.startswith("DTEND")), None)
            if not dt_line:
                continue

        try:
            due_date, due_time = parse_ics_date(dt_line)
        except Exception:
            continue  # skip bad date

        course = title
        course_id = parse_course_id(title)

        existing = None
        if uid:
            existing = Assignment.query.filter_by(user_id=user.id, ics_uid=uid).first()
        if not existing:
            existing = Assignment.query.filter_by(user_id=user.id, name=title).first()

        if existing:
            if existing.due_date != due_date:
                existing.due_date = due_date
            if due_time and existing.due_time != due_time:
                existing.due_time = due_time

            existing.course = course
            existing.course_id = course_id
            existing.ics_uid = uid or existing.ics_uid

        else:
            assignment = Assignment(
                name=title,
                due_date=due_date,
                user_id=user.id,
                ics_uid=uid,
                course=course,
                course_id=course_id,
                due_time=due_time,
                assignment_type=None,
                priority_level=None,
                points=None
            )
            db.session.add(assignment)

        if uid:
            seen_uids.add(uid)
        else:
            seen_titles.add(title)

        # DEBUG: show parsed assignment data and where it maps
        print(f"[sync] user={user.username} title={title!r} uid={uid!r} due_date={due_date} due_time={due_time} course_id={course_id}")

    # Delete stale assignments that are no longer in the calendar feed
    existing_assignments = Assignment.query.filter_by(user_id=user.id).all()
    for assignment in existing_assignments:
        if assignment.ics_uid:
            if assignment.ics_uid not in seen_uids:
                db.session.delete(assignment)
        else:
            if assignment.name not in seen_titles:
                db.session.delete(assignment)

    db.session.commit()