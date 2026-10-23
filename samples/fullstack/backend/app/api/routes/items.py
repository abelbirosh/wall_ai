from fastapi import APIRouter

router = APIRouter(prefix="/items", tags=["items"])


@router.get("/")
def read_items():
    return []


@router.get("/{id}")
def read_item(id: int):
    return {"id": id}
