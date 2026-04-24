import requests
import sys

api_key = "AIzaSyAJcA7BDrEno7IzktyxbgRS4JkQdJYD2EM"
models_to_test = ["gemini-flash-latest", "gemini-1.5-flash", "gemini-1.5-flash-latest", "gemini-1.5-pro"]

prompt = "Hello"
payload = {
    "contents": [{"parts": [{"text": prompt}]}],
    "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
}

for model in models_to_test:
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    try:
        resp = requests.post(f"{endpoint}?key={api_key}", json=payload, timeout=10)
        print(f"{model}: {resp.status_code}")
        if resp.status_code != 200:
            print(f"  {resp.text}")
    except Exception as e:
        print(f"{model}: Error {e}")
