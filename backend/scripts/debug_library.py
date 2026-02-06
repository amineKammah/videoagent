import sys
import os
import time
sys.path.append(os.path.join(os.path.dirname(__file__), "../src"))
from videoagent.library import VideoLibrary, get_storage_client

def debug_library():
    print("Initializing Library (Global)...")
    lib = VideoLibrary()
    
    print("Listing first 20 files in bucket to verify paths:")
    count = 0
    for blob in lib.storage.list_files("", recursive=True):
        print(f" - {blob}")
        count += 1
        if count >= 20:
            break
            
    print("-" * 20)
    
    company_id = "10d48e59-6717-40f2-8e97-f10d7ad51ebb"
    print(f"Initializing Library for Company: {company_id}")
    lib_company = VideoLibrary(company_id=company_id)
    print(f"Video Prefix: {lib_company._video_prefix}")
    
    print("Running scan_library(force_reindex=True)...")
    videos = lib_company.scan_library(force_reindex=True)
    print(f"Found {len(videos)} videos.")
    for v in videos[:5]:
        print(f" - {v.filename} ({v.id})")

if __name__ == "__main__":
    debug_library()
