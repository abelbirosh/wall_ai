from sqlmodel import create_engine

from app.core.config import settings

engine = create_engine(f"postgresql+psycopg://app@{settings.POSTGRES_SERVER}/app")
