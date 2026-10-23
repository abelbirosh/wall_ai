from fastapi import Depends
from sqlmodel import Session

from app.core.db import engine


def get_db():
    with Session(engine) as session:
        yield session


def get_current_user(db=Depends(get_db)):
    return {"id": 1}
