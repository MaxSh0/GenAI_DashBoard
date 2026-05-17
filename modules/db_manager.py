"""Database connection and session management for the GenAI dashboard."""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modules.models import Base

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://genai_admin:superpassword@localhost:5432/genai_platform")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Create all tables if they do not already exist.

    Uses SQLAlchemy's metadata.create_all to ensure the database schema
    matches the ORM model definitions in modules.models.
    """
    Base.metadata.create_all(bind=engine)


def get_db():
    """Yield a database session for use as a FastAPI dependency.

    Yields:
        sqlalchemy.orm.Session: A new SQLAlchemy session.

    The session is automatically closed when the request finishes,
    even if an exception occurs.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
