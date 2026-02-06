"""
Migration script to remove audio from all videos in the GCS library.
It creates a parallel structure for voiceless videos.

Usage:
    python backend/scripts/migrate_audio_removal.py
"""
import os
import sys
import tempfile
import subprocess
from pathlib import Path
from tqdm import tqdm

# Add backend to path so we can import videoagent modules
sys.path.append(os.path.join(os.path.dirname(__file__), "../src"))

from videoagent.storage import get_storage_client

def strip_audio(input_path: Path, output_path: Path):
    """Strip audio from video using ffmpeg."""
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_path),
        "-c", "copy",
        "-an",
        str(output_path)
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def main():
    print("Initializing GCS client...")
    try:
        storage = get_storage_client()
    except Exception as e:
        print(f"Error initializing storage client: {e}")
        return

    print(f"Scanning bucket: {storage.bucket_name}...")
    
    # List all files
    all_blobs = list(storage.list_files("", recursive=True))
    video_blobs = [b for b in all_blobs if b.endswith(('.mp4', '.mov', '.avi', '.mkv', '.webm'))]
    
    print(f"Found {len(video_blobs)} video files.")

    videos_to_process = []
    
    for blob_path in video_blobs:
        # Skip if already in a voiceless folder
        if "videos_voiceless/" in blob_path:
            continue
            
        # Determine target path
        # videos/foo.mp4 -> videos_voiceless/foo.mp4
        # companies/123/videos/bar.mp4 -> companies/123/videos_voiceless/bar.mp4
        
        target_path = blob_path.replace("/videos/", "/videos_voiceless/")
        if target_path == blob_path:
            # Fallback for root level videos if any (though usually in videos/)
            if blob_path.startswith("videos/"):
                 target_path = blob_path.replace("videos/", "videos_voiceless/", 1)
            else:
                 print(f"Skipping weird path: {blob_path}")
                 continue

        if not storage.exists(target_path):
            videos_to_process.append((blob_path, target_path))

    print(f"Found {len(videos_to_process)} videos that need audio removal.")
    
    if not videos_to_process:
        print("All videos are up to date.")
        return

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        for src_blob, dst_blob in tqdm(videos_to_process, desc="Processing videos"):
            try:
                local_src = temp_path / "input.mp4"
                local_dst = temp_path / "output.mp4"
                
                # Download
                storage.download_to_filename(src_blob, local_src)
                
                # Strip audio
                strip_audio(local_src, local_dst)
                
                # Upload
                storage.upload_from_filename(dst_blob, local_dst, content_type="video/mp4")
                
                # Cleanup
                if local_src.exists(): os.remove(local_src)
                if local_dst.exists(): os.remove(local_dst)
                
            except Exception as e:
                print(f"Failed to process {src_blob}: {e}")

    print("Migration complete!")

if __name__ == "__main__":
    main()
