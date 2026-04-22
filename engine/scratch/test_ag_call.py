import asyncio
import os
import sys
from pathlib import Path

# Add workspace to sys.path
sys.path.append(str(Path(__file__).parent.parent.parent))

from engine.llm_caller import _ag_token_cache, _AG_API_URL, _AG_USER_AGENT
import urllib.request
import json
import gzip

async def main():
    print("--- Probing Antigravity generateContent ---")
    try:
        access_token, project_id = await _ag_token_cache.ensure_valid()
        print(f"Project ID: {project_id}")
        
        # Test model: gemini-3-flash-agent (found in previous probe)
        model = "gemini-3-flash-agent"
        
        url = f"{_AG_API_URL}/v1internal:generateContent"
        
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": "Hello, who are you?"}]
                }
            ],
            "generationConfig": {
                "maxOutputTokens": 2048,
                "temperature": 0.7
            }
        }
        
        body_dict = {
            "model": model,
            "project": project_id,
            "request": payload
        }
        
        import uuid
        req = urllib.request.Request(url, data=json.dumps(body_dict).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {access_token}")
        req.add_header("User-Agent", _AG_USER_AGENT)
        req.add_header("requestType", "agent")
        req.add_header("requestId", f"req-{uuid.uuid4()}")
        
        print(f"Calling URL: {url}")
        # print(f"Body: {json.dumps(body_dict, indent=2)}")
        
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            data = json.loads(raw.decode())
            print("Success!")
            print(json.dumps(data, indent=2))
            
    except Exception as e:
        print(f"Error: {e}")
        if hasattr(e, 'read'):
            try:
                err_body = e.read()
                if err_body[:2] == b"\x1f\x8b":
                    err_body = gzip.decompress(err_body)
                print(f"Error Body: {err_body.decode()}")
            except:
                pass

if __name__ == "__main__":
    asyncio.run(main())
