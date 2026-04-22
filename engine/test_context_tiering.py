import asyncio
import logging
from engine.agent_engine import AgentEngine

logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")

async def test_context_tiering():
    print("🚀 Starting Context Tiering Stress Test...")
    engine = AgentEngine(working_dir="d:/ai/workspace")
    await engine.initialize()
    
    print("\n--- 0. Pre-seeding Memory ---")
    engine.memory.remember("Preferred coding style is functional and clean.", category="coding_style")
    
    # Add initial system prompt
    # type: ignore
    engine._messages.append({"role": "system", "content": "You are a helpful assistant."})
    
    # Lower threshold for testing
    engine.compactor.threshold = 5000
    print(f"Set compaction threshold to {engine.compactor.threshold} tokens.")
    print("\n--- 1. Generating massive dummy context ---")
    for i in range(50):
        # type: ignore (Intentionally accessing protected member for stress test)
        engine._messages.append({"role": "user", "content": f"Dummy question {i}"})
        # Simulate long output from a tool or model
        engine._messages.append({"role": "assistant", "content": "A" * 1000}) 
        
    # type: ignore
    print(f"Generated {len(engine._messages)} messages.")
    
    # Force token calculation to simulate threshold breach (assuming gemini counting logic)
    print("\n--- 2. Triggering Enforce Token Budget ---")
    await engine._enforce_token_budget()
    
    print("\n--- 3. Verifying Results ---")
    # type: ignore
    print(f"Messages count after compaction: {len(engine._messages)}")
    # type: ignore
    if engine._messages and engine._messages[0].get("role") == "system":
        print("✅ System prompt preserved")
        # type: ignore
        if any("<conversation_summary>" in str(m.get("content", "")) for m in engine._messages):
            print("✅ Recursive Summary injected successfully!")
    else:
        # type: ignore
        print(f"❌ System prompt not at index 0. Actual role: {engine._messages[0].get('role')}")
    
    print("\n--- 4. Testing Semantic Recall Injection ---")
    await engine._inject_semantic_recall("coding style")
    # type: ignore
    if engine._messages[1].get("role") == "system" and "<semantic_recall>" in str(engine._messages[1].get("content")):
         print("✅ Semantic Recall temporarily injected successfully!")
    else:
        # type: ignore
        print(f"❌ Semantic recall injection failed or at wrong index. Index 1 role: {engine._messages[1].get('role')}")
        # type: ignore
        # print(f"Index 1 content: {engine._messages[1].get('content')}")
         
    await engine.shutdown()

if __name__ == "__main__":
    asyncio.run(test_context_tiering())
