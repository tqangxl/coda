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
    print("--- Probing Antigravity Models ---")
    try:
        access_token, project_id = await _ag_token_cache.ensure_valid()
        print(f"Project ID: {project_id}")
        
        url = f"{_AG_API_URL}/v1internal:fetchAvailableModels"
        req = urllib.request.Request(url, data=b"{}", method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {access_token}")
        req.add_header("User-Agent", _AG_USER_AGENT)
        
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            data = json.loads(raw.decode())
            print(json.dumps(data, indent=2))
            
    except Exception as e:
        print(f"Error: {e}")
        if hasattr(e, 'read'):
            print(f"Body: {e.read().decode()}")

if __name__ == "__main__":
    asyncio.run(main())
