import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from modules.models import Base

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://genai_admin:superpassword@localhost:5432/genai_platform")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Создает таблицы, если их нет."""
    Base.metadata.create_all(bind=engine)

def get_db():
    """Генератор сессии для работы в коде."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()