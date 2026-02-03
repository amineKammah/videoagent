
import json
import os
import sys
from pathlib import Path

# Setup Path
# Assuming running from repo root
sys.path.append(os.path.join(os.getcwd(), 'backend/src'))

from videoagent.db import connection, models
from videoagent.db.crud import get_company_by_name, create_user, create_customer_profile, list_users

BASE_DATA_DIR = Path("/Users/amineka/Downloads/merged_data")

# Directory Name -> DB Name
COMPANY_MAPPING = {
    "appfolio": "Appfolio",
    "gusto": "Gusto",
    "toast": "Toast",
    "zendesk": "Zendesk"
}

def import_prospects():
    with connection.get_db_context() as db:
        for slug, db_name in COMPANY_MAPPING.items():
            print(f"Processing {db_name}...")
            
            # 1. Get Company
            company = get_company_by_name(db, db_name)
            if not company:
                print(f"  -> Company '{db_name}' not found in DB. Videoagent DB might need 'migrate_companies.py' first if this is unexpected. Skipping.")
                continue
                
            # 2. Get User
            # Try to find ANY user for this company, or create a default one
            users = list_users(db, company_id=company.id)
            if users:
                user = users[0]
            else:
                email = f"demo@{slug}.com"
                print(f"  -> No user found. Creating {email}...")
                user = create_user(db, company.id, email, f"{db_name} Admin")
            
            print(f"  -> Using user: {user.name} ({user.id})")

            # 3. Read JSON
            json_path = BASE_DATA_DIR / slug / "_Prospects" / "prospects.json"
            if not json_path.exists():
                print(f"  -> No prospects.json found at {json_path}")
                continue
                
            with open(json_path, 'r') as f:
                prospects = json.load(f)
                
            print(f"  -> Found {len(prospects)} prospects.")
            
            # 4. Import
            count = 0
            for p in prospects:
                # Check duplicate by name for this user/company
                existing = db.query(models.CustomerProfile).filter(
                    models.CustomerProfile.company_id == company.id,
                    models.CustomerProfile.created_by_user_id == user.id,
                    models.CustomerProfile.name == p['name']
                ).first()
                
                if existing:
                    # Skip existing
                    continue
                
                # Prepare profile_data with extra fields
                # Everything that isn't a core column goes into profile_data
                profile_data = {
                    "company_size": p.get("company_size"),
                    "enrichment": p.get("enrichment", {})
                }
                
                # Add any other top-level keys that aren't core
                core_keys = {"name", "title", "company", "industry"}
                for k, v in p.items():
                    if k not in core_keys and k != "company_size" and k != "enrichment":
                        profile_data[k] = v

                create_customer_profile(
                    db,
                    company_id=company.id,
                    created_by_user_id=user.id,
                    name=p['name'],
                    title=p.get('title'),
                    customer_company=p.get('company'), # Map 'company' from JSON to 'customer_company'
                    industry=p.get('industry'),
                    profile_data=profile_data
                )
                count += 1
            
            print(f"  -> Imported {count} new prospects.")

if __name__ == "__main__":
    import_prospects()
