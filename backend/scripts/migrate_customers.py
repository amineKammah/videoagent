
"""
Migrate legacy customers to user-specific CustomerProfile.
Target: Company 'Navan', First User.
"""
import sys
import os
import sqlite3
import uuid
import json
from pathlib import Path

# Add backend/src to path
sys.path.append(os.path.join(os.getcwd(), 'backend/src'))

from videoagent.db import connection, models
from videoagent.db.crud import get_company_by_name, list_users, create_customer_profile

def migrate():
    print("Starting customer migration...")
    
    # 1. Get Target Context (Navan + First User)
    with connection.get_db_context() as db:
        company = get_company_by_name(db, "Navan")
        if not company:
            print("Error: Company 'Navan' not found. Please run migrate_companies.py first or create it.")
            return

        users = list_users(db, company_id=company.id)
        if not users:
            print(f"Error: No users found for company '{company.name}'.")
            return
        
        target_user = users[0]
        print(f"Targeting Company: {company.name} ({company.id})")
        print(f"Targeting User: {target_user.name} ({target_user.id})")

        # 2. Read Legacy Customers
        # We access the raw sqlite DB to get the 'customers' table which is not in ORM models
        # Use the raw connection from the engine or just connect directly
        db_path = Path("backend/data/videoagent.db") # Adjusted path? 
        # Actually videoagent.db is in repo root usually or backend/videoagent.db?
        # database.py says: REPO_ROOT / "videoagent.db"
        # Let's try to find it.
        repo_root = Path.cwd()
        possible_paths = [
            repo_root / "videoagent.db",
            repo_root / "backend" / "videoagent.db",
            repo_root / "backend" / "data" / "videoagent.db"
        ]
        
        sqlite_path = None
        for p in possible_paths:
            if p.exists():
                sqlite_path = p
                break
        
        if not sqlite_path:
            print("Error: videoagent.db not found.")
            return

        print(f"Reading from {sqlite_path}")
        conn = sqlite3.connect(sqlite_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT * FROM customers")
            legacy_customers = [dict(row) for row in cursor.fetchall()]
        except sqlite3.OperationalError:
            print("Table 'customers' does not exist. No legacy data to migrate.")
            legacy_customers = []
        finally:
            conn.close()

        print(f"Found {len(legacy_customers)} legacy customers.")

        # 3. Import into CustomerProfile
        migrated_count = 0
        for cust in legacy_customers:
            # Check if exists (by name for this user?)
            existing = db.query(models.CustomerProfile).filter(
                models.CustomerProfile.company_id == company.id,
                models.CustomerProfile.name == cust['name']
            ).first()
            
            if existing:
                print(f"Skipping {cust['name']} (already exists)")
                continue

            # Map fields
            # Legacy: id, brand_id, name, title, company, industry, company_size, created_at, ...
            profile_data = {
                "brand_id": cust.get("brand_id"),
                "company_size": cust.get("company_size"),
                "pain_points": cust.get("pain_points"), # If exists
                "legacy_id": cust.get("id")
            }
            
            # Map extra fields into profile_data
            known_fields = {"id", "brand_id", "name", "title", "company", "industry", "company_size", "created_at"}
            for k, v in cust.items():
                if k not in known_fields:
                    profile_data[k] = v

            new_profile = create_customer_profile(
                db,
                company_id=company.id,
                created_by_user_id=target_user.id,
                name=cust['name'],
                title=cust.get('title'),
                customer_company=cust.get('company'), # confusing naming in legacy 'company' field vs 'customer_company'
                industry=cust.get('industry'),
                profile_data=profile_data
            )
            migrated_count += 1
            print(f"Migrated: {new_profile.name}")

        print(f"Migration complete. {migrated_count} records created.")

if __name__ == "__main__":
    migrate()
