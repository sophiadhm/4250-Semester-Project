from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db, Base, engine
from app.schemas import AssignmentCreate, AssignmentUpdate, AssignmentResponse
from app.models import Assignment

Base.metadata.create_all(bind=engine)

app = FastAPI()