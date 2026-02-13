from sqlalchemy import Column, Integer, String, Float, CheckConstraint
from app.database import Base

class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, index=True)

    course_id = Column(String(4), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "course_id GLOB '[0-9][0-9][0-9][0-9]'",
            name="course_id_must_be_4_digits"
        ),
    )

    name = Column(String, index=True)
    course = Column(String)
    due_date = Column(String)
    due_time = Column(String)
    assignment_type = Column(String)
    priority_level = Column(Integer)
    points = Column(Float)
