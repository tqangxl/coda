import httpx
import json

def test():
    url = "http://localhost:11434/v1/chat/completions"
    data = {
        "model": "qwen3.5:4b",
        "messages": [{"role": "user", "content": "ping"}],
        "temperature": 0
    }
    try:
        print(f"Sending request to {url}...")
        res = httpx.post(url, json=data, timeout=30.0)
        print(f"Status: {res.status_code}")
        print(f"Response: {res.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test()
