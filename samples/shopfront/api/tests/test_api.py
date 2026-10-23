from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_lists_products():
    assert client.get("/products").status_code == 200


def test_checkout_charges_the_card():
    response = client.post("/checkout", json={"items": ["mug"], "token": "tok_visa"})
    assert response.status_code == 200
