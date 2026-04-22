import asyncio
from engine.db import SurrealStore

async def test():
    s = SurrealStore()
    if await s.connect():
        res = await s.select_all("agent_identity")
        print(f"Identities: {res}")
        await s.disconnect()

if __name__ == "__main__":
    asyncio.run(test())
