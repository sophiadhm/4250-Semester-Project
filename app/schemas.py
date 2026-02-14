from pydantic import BaseModel, StringConstraints
from typing import Annotated

CourseID = Annotated[
    str,
    StringConstraints(pattern=r'^\d{4}$')
]

class AssignmentBase(BaseModel):
    name: str
    course: str
    course_id: CourseID
    due_date: str
    due_time: str
    assignment_type: str
    priority_level: int
    points: float


class AssignmentCreate(AssignmentBase):
    pass


class AssignmentUpdate(BaseModel):
    name: str | None = None
    course: str | None = None
    course_id: CourseID | None = None
    due_date: str | None = None
    due_time: str | None = None
    assignment_type: str | None = None
    priority_level: int | None = None
    points: float | None = None


class AssignmentResponse(AssignmentBase):
    id: int

    class Config:
        from_attributes = True  
