import os
import requests

api_key = "sk_30a66ac7f007261c000b158e7f61d628cf7932c28eab75a6"
url = "https://api.elevenlabs.io/v1/text-to-speech/EXAVITQu4vr4xnSDxMaL"
headers = {
    "xi-api-key": api_key,
    "Content-Type": "application/json"
}
data = {
    "text": "test",
    "model_id": "eleven_monolingual_v1"
}
try:
    response = requests.post(url, json=data, headers=headers)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text[:200]}")
except Exception as e:
    print(f"Error: {e}")
