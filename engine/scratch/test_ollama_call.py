import asyncio
import os
from engine.llm_caller import OllamaCaller

async def test():
    os.environ["OLLAMA_MODEL_NAME"] = "qwen3.5:4b"
    caller = OllamaCaller()
    print(f"Calling Ollama with model: {caller.model_name}")
    try:
        res = await caller.call([{"role": "user", "content": "hello"}])
        print(f"Response: {res.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test())
