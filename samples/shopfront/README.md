# shopfront sample

A small two-service target with a known structure, used to check what the Understand component finds. `expected.json` is the ground truth.

- **api** (Python, FastAPI): serves `GET /products` and `POST /checkout`, and charges cards through Stripe.
- **notifier** (TypeScript, Express): serves `POST /notify` and `GET /digest`, sends email through SendGrid, and calls the api's `GET /products`.

Planted cases:

- an external URL inlined in the call (Stripe) and one held in a constant (SendGrid);
- a call between the two services, through the `api` hostname;
- inline route handlers in Express;
- one function that is never called (`legacy_discount`).
