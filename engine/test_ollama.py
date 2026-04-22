import os
import asyncio
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ollama_test")

def load_env():
    env_path = Path("d:/ai/workspace/.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                k, v = key.strip(), value.strip()
                os.environ[k] = v
        logger.info("Loaded .env")

async def test_ollama():
    load_env()
    from engine.llm_caller import create_caller
    
    model_name = os.getenv("DEFAULT_MODEL_NAME", "glm-5.1:cloud")
    logger.info(f"Testing model: {model_name}")
    
    caller = create_caller(model_name)
    
    messages = [{"role": "user", "content": "你好，请确认你的模型名称和版本。"}]
    
    try:
        response = await caller.call(messages)
        logger.info("✅ Ollama Response Received:")
        logger.info(f"Text: {response.text}")
        logger.info(f"Tokens: {response.input_tokens}/{response.output_tokens}")
    except Exception as e:
        logger.error(f"❌ Ollama Test Failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_ollama())
