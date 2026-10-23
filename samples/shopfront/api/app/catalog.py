PRODUCTS = {"mug": 1200, "shirt": 2500}


def all_products():
    return [{"sku": sku, "price": price} for sku, price in PRODUCTS.items()]


def price_of(items):
    return sum(PRODUCTS[sku] for sku in items)


def legacy_discount(total):
    # Never called: the model should flag this as unused.
    return int(total * 0.9)
