"""
Script to migrate annotations from videoagent.db (sqlite) to the configured DB (via SQLAlchemy).
"""
import sqlite3
import os
import sys
from pathlib import Path

# Add src to path
# Add src to path
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.append(str(REPO_ROOT / "backend/src"))
LEGACY_DB_PATH = REPO_ROOT / "videoagent.db"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from videoagent.db.models import Annotation, SessionAnnotatorStatus, SessionGlobalStatus, Base
from videoagent.db.connection import DATABASE_URL, engine

def get_legacy_connection():
    if not LEGACY_DB_PATH.exists():
        print(f"Legacy DB not found at {LEGACY_DB_PATH.resolve()}")
        return None
    print(f"Opening legacy DB at {LEGACY_DB_PATH.resolve()}")
    conn = sqlite3.connect(LEGACY_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def migrate():
    print(f"Migrating from legacy videoagent.db to {DATABASE_URL}")
    
    # 1. Connect to Legacy DB
    legacy_conn = get_legacy_connection()
    if not legacy_conn:
        return

    # 2. Connect to New DB (SQLAlchemy)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    # Ensure tables exist
    Base.metadata.create_all(engine)

    # 3. Migrate Annotations
    print("Migrating Annotations...")
    try:
        cursor = legacy_conn.cursor()
        cursor.execute("SELECT * FROM annotations")
        rows = cursor.fetchall()
        
        count = 0
        for row in rows:
            # Check if exists
            exists = session.query(Annotation).filter_by(id=row["id"]).first()
            if exists:
                continue

            # Handle rejected column which might be missing in very old DBs
            rejected = False
            if "rejected" in row.keys():
                rejected = bool(row["rejected"])

            # Use .keys() to check if company_id exists in row
            company_id = row["company_id"] if "company_id" in row.keys() else None

            ann = Annotation(
                id=row["id"],
                company_id=company_id,
                session_id=row["session_id"],
                scene_id=row["scene_id"],
                timestamp=row["timestamp"],
                global_timestamp=row["global_timestamp"],
                annotator_id=row["annotator_id"],
                annotator_name=row["annotator_name"],
                category=row["category"],
                description=row["description"],
                severity=row["severity"],
                created_at=row["created_at"], # SQLAlchemy handles string->datetime if simple ISO
                updated_at=row["updated_at"],
                resolved=bool(row["resolved"]),
                resolved_by=row["resolved_by"],
                rejected=rejected,
            )
            session.add(ann)
            count += 1
        
        session.commit()
        print(f"Migrated {count} annotations.")

    except Exception as e:
        print(f"Error migrating annotations: {e}")
        session.rollback()

    # 4. Migrate Session Statuses
    print("Migrating Session Statuses...")
    try:
        # SessionGlobalStatus
        cursor.execute("SELECT * FROM session_status")
        rows = cursor.fetchall()
        count = 0
        for row in rows:
            if not session.query(SessionGlobalStatus).filter_by(session_id=row["session_id"]).first():
                st = SessionGlobalStatus(
                    session_id=row["session_id"],
                    status=row["status"],
                    updated_at=row["updated_at"]
                )
                session.add(st)
                count += 1
        session.commit()
        print(f"Migrated {count} global session statuses.")

        # SessionAnnotatorStatus
        cursor.execute("SELECT * FROM session_annotator_status")
        rows = cursor.fetchall()
        count = 0
        for row in rows:
            if not session.query(SessionAnnotatorStatus).filter_by(
                session_id=row["session_id"], annotator_id=row["annotator_id"]
            ).first():
                st = SessionAnnotatorStatus(
                    session_id=row["session_id"],
                    annotator_id=row["annotator_id"],
                    status=row["status"],
                    updated_at=row["updated_at"]
                )
                session.add(st)
                count += 1
        session.commit()
        print(f"Migrated {count} annotator statuses.")

    except Exception as e:
        print(f"Error migrating statuses: {e}")
        # Tables might not exist in old DB
        session.rollback()

    session.close()
    legacy_conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate()
