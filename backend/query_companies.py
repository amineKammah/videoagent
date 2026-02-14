
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from videoagent.db.models import Company

# DATABASE_URL from env or default to postgres
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("DATABASE_URL not set. Exiting.")
    sys.exit(1)

print(f"Connecting to {DATABASE_URL.split('@')[-1]}...")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
session = SessionLocal()

try:
    stmt = select(Company)
    companies = session.execute(stmt).scalars().all()
    
    print(f"Found {len(companies)} companies:")
    for company in companies:
        print(f"ID: {company.id}, Name: {company.name}, Created: {company.created_at}")
        # print(f"  Settings: {company.settings}")

except Exception as e:
    print(f"Error: {e}")
finally:
    session.close()
