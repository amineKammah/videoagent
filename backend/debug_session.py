from videoagent.db import connection, crud
from videoagent.agent.service import VideoAgentService
from fastapi import HTTPException
import uuid

# Replicate api.create_agent_session logic
try:
    with connection.get_db_context() as db:
        # 1. List users (bootstrap logic)
        users = crud.list_users(db, limit=1)
        if not users:
            print("[ERROR] No users found in DB!")
            exit(1)
            
        user = users[0]
        print(f"[INFO] Found user: {user.id} ({user.email})")
        
        # 2. Mimic Service logic
        service = VideoAgentService()
        try:
            session_id = service.create_session(user_id=user.id, company_id=user.company_id)
            print(f"[SUCCESS] Created session: {session_id}")
            
            # 3. Verify it exists
            s = crud.get_session(db, session_id)
            if s:
                print(f"[VERIFIED] Session found in DB: {s.id}, Owner: {s.user_id}")
            else:
                print(f"[ERROR] Session NOT found in DB after creation!")
        except Exception as e:
            print(f"[ERROR] create_session failed: {e}")
            import traceback
            traceback.print_exc()

except Exception as e:
    print(f"[FATAL] Script failed: {e}")
