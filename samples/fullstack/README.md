# fullstack sample

A small FastAPI backend and React frontend that reproduce patterns from real codebases (modeled on the FastAPI full-stack template). `expected.json` is the ground truth.

Planted cases:

- routers mounted under prefixes, one of them from a settings constant (`/api/v1` + `/users`);
- functions the framework calls, not the code: FastAPI dependencies (`Depends(get_db)`), a Pydantic computed field, a function passed as an argument, a `__main__` entry point and Alembic migrations;
- a method called through `self`;
- React components used as JSX, and a handler passed as a prop;
- imports through a tsconfig path alias (`@/...`), including a barrel file that re-exports the SDK;
- a generated API client that calls the backend by relative URL;
- services reached through SDKs and config, not URLs: Postgres (compose image and connection string), SMTP (`emails`) and Sentry (`sentry_sdk`);
- three genuinely unused functions.
