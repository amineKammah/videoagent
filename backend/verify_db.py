import os
import sys
from sqlalchemy import create_engine, text

# Read from .env manually to avoid dependency
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    with open(env_path, 'r') as f:
        for line in f:
            if line.strip() and not line.startswith('#'):
                key, value = line.strip().split('=', 1)
                os.environ[key] = value

url = os.environ.get("DATABASE_URL")
if not url:
    print("DATABASE_URL not found")
    sys.exit(1)

print(f"Testing connection to: {url.split('@')[-1]}") # Print only host part for safety

try:
    engine = create_engine(url)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1")).scalar()
        print(f"Connection Successful! Result: {result}")
except Exception as e:
    print(f"Connection Failed: {e}")
    sys.exit(1)
