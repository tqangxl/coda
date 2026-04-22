import os
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("model_check")

def load_env():
    env_path = Path("d:/ai/workspace/.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                k, v = key.strip(), value.strip()
                os.environ[k] = v
                if k == "GEMINI_PROXY":
                    os.environ["HTTP_PROXY"] = v
                    os.environ["HTTPS_PROXY"] = v
        logger.info("Loaded .env")

load_env()

try:
    from google import genai
    api_key = os.getenv("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    
    logger.info("Listing models...")
    for model in client.models.list():
        print(f"Model: {model.name}")
except Exception as e:
    logger.error(f"Failed to list models: {e}")
