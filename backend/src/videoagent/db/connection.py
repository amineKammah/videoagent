"""
Database connection handling for SQLAlchemy.

Switch DATABASE_URL to migrate between SQLite and PostgreSQL.
"""
import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Switch this string to migrate databases
# SQLite: sqlite:///videoagent.db
# PostgreSQL: postgresql://user:pass@host/dbname
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///videoagent.db")

# For SQLite, we need check_same_thread=False for multi-threaded access
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency for database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context():
    """Context manager for database sessions outside of FastAPI."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
