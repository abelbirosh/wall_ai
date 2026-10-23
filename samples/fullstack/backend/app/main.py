import sentry_sdk
from fastapi import FastAPI

from app.api.main import api_router
from app.core.config import settings


def custom_generate_unique_id(route):
    return f"{route.tags[0]}-{route.name}"


if settings.SENTRY_DSN:
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN))

app = FastAPI(generate_unique_id_function=custom_generate_unique_id)
app.include_router(api_router, prefix=settings.API_V1_STR)
