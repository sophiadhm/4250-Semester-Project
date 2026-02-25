from sqlalchemy import Column, Integer, String, Float, CheckConstraint
from app.database import Base
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(150), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

    def set_password(self, password):        
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
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
