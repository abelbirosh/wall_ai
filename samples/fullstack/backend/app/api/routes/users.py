from fastapi import APIRouter, Depends

from app import crud, utils
from app.api.deps import get_current_user

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/")
def read_users(user=Depends(get_current_user)):
    return crud.get_users()


@router.post("/")
def create_user(body: dict):
    created = crud.create_user(body)
    utils.send_email(body["email"], "Welcome")
    return created
