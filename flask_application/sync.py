# sync.py
import requests
from datetime import datetime
from app.models import db, Assignment

def parse_ics_date(ics_date_str):
    # Example: 20260313T235900Z -> datetime
    return datetime.strptime(ics_date_str[:15], "%Y%m%dT%H%M%S")

def sync_assignments(user):
    if not user.ics_url:
        return

    response = requests.get(user.ics_url)
    ics_text = response.text

    # Split into events
    events = ics_text.split("BEGIN:VEVENT")[1:]  # skip first part

    for event_text in events:
        # Get title
        title_line = next((line for line in event_text.splitlines() if line.startswith("SUMMARY:")), None)
        title = title_line.replace("SUMMARY:", "").strip() if title_line else "No Title"

        # Get due date
        dt_line = next((line for line in event_text.splitlines() if line.startswith("DTSTART")), None)
        if dt_line:
            due_date = parse_ics_date(dt_line.split(":")[1].strip())
        else:
            continue  # skip events without a date

        # Check for duplicates
        existing = Assignment.query.filter_by(
            title=title,
            due_date=due_date,
            user_id=user.id
        ).first()

        if not existing:
            assignment = Assignment(title=title, due_date=due_date, user_id=user.id)
            db.session.add(assignment)

    db.session.commit()