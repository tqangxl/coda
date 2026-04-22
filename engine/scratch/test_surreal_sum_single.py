import asyncio
from engine.db import SurrealStore

async def test_sum_single_record_group():
    store = SurrealStore()
    await store.connect("ws://127.0.0.1:11001/rpc", "root", "AgentSecurePass2026", "ai_agents_v2", "agent_system")
    
    await store.execute_query("DELETE agent_ledger")
    await store.execute_query("CREATE agent_ledger CONTENT { team_id: 'test', cost: 0.1 }")
    
    print("Testing GROUP BY query with single record...")
    try:
        res = await store.execute_query("SELECT team_id, math::sum(cost) as total_used FROM agent_ledger GROUP BY team_id")
        print(f"Result: {res}")
    except Exception as e:
        print(f"Query failed: {e}")

    await store.disconnect()

if __name__ == "__main__":
    asyncio.run(test_sum_single_record_group())
