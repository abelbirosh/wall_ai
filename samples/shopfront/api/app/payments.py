import httpx


def charge(amount, token):
    response = httpx.post(
        "https://api.stripe.com/v1/charges",
        data={"amount": amount, "currency": "usd", "source": token},
    )
    return response.json()
