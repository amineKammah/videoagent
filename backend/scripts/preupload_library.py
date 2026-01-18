from videoagent.config import default_config
from videoagent.gemini import GeminiClient
from videoagent.library import VideoLibrary


def main() -> None:
    from tqdm import tqdm

    config = default_config
    library = VideoLibrary(config)
    library.scan_library()
    videos = library.list_videos()
    if not videos:
        print("No videos found in the library.")
        return

    client = GeminiClient(config)
    uploaded = 0
    for video in tqdm(videos, desc="Preuploading videos", unit="video"):
        file_obj = client.get_or_upload_file(video.path)
        file_name = getattr(file_obj, "name", None) or getattr(file_obj, "id", None)
        if file_name:
            uploaded += 1

    print(f"Preupload complete: {uploaded}/{len(videos)} videos cached.")


if __name__ == "__main__":
    main()
