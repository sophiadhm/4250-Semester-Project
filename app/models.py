from sqlalchemy import Column, Integer, String, Float
from app.database import Base

class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    course = Column(String)
    course_id = Column(Integer)
    due_date = Column(String)
    due_time = Column(String)
    assignment_type = Column(String)
    priority_level = Column(Integer)
    points = Column(Float)