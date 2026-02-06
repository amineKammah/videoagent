import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "../src"))
from videoagent.storage import get_storage_client

def verify():
    storage = get_storage_client()
    print(f"Checking bucket {storage.bucket_name} for voiceless videos...")
    
    found = False
    count = 0
    for blob in storage.list_files("videos_voiceless/", recursive=True):
        print(f"Found voiceless video: {blob}")
        found = True
        count += 1
        if count >= 5:
            break
            
    if not found:
        # Check company folders
        print("Checking company folders...")
        for blob in storage.list_files("companies/", recursive=True):
            if "videos_voiceless/" in blob:
                print(f"Found voiceless video: {blob}")
                found = True
                count += 1
                if count >= 5:
                    break
    
    if found:
        print("SUCCESS: Found voiceless videos.")
    else:
        print("WARNING: No voiceless videos found yet.")

if __name__ == "__main__":
    verify()
