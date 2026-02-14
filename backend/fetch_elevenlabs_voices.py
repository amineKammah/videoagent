import os
import requests
import json

def fetch_voices():
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        print("Error: ELEVENLABS_API_KEY not found in environment.")
        return

    url = "https://api.elevenlabs.io/v1/voices"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        voices_data = response.json()
        
        # Filter/Process if needed, or just dump all
        voices = voices_data.get("voices", [])
        
        processed_voices = []
        for voice in voices:
            # We want ID, Name, Category (optional), Sample URL
            processed_voices.append({
                "id": voice["voice_id"],
                "name": voice["name"],
                "category": voice.get("category"),
                "sample_url": voice.get("preview_url")
            })

        print(json.dumps(processed_voices, indent=2))

    except Exception as e:
        print(f"Error fetching voices: {e}")

if __name__ == "__main__":
    fetch_voices()
