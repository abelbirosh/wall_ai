from fastapi import FastAPI

from app import catalog, payments

app = FastAPI()


@app.get("/products")
def list_products():
    return catalog.all_products()


@app.post("/checkout")
def checkout(order: dict):
    total = catalog.price_of(order["items"])
    return payments.charge(total, order["token"])
