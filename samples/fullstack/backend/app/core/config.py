from pydantic import computed_field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"
    POSTGRES_SERVER: str = "db"
    SMTP_HOST: str | None = None
    SENTRY_DSN: str | None = None

    @computed_field
    @property
    def emails_enabled(self) -> bool:
        return self._has_smtp()

    def _has_smtp(self) -> bool:
        return bool(self.SMTP_HOST)


settings = Settings()
