import asyncio
import os
from engine.db import SurrealStore

async def test():
    store = SurrealStore()
    if await store.connect():
        print("Connected")
        # SurrealDB 1.x info query
        res = await store._safe_query("INFO FOR DB")
        print(f"Raw Res Type: {type(res)}")
        print(f"Raw Res: {res}")
        if res and isinstance(res, list):
            for i, item in enumerate(res):
                print(f"Item {i} Type: {type(item)}")
                print(f"Item {i}: {item}")
        await store.disconnect()
    else:
        print("Failed to connect")

if __name__ == "__main__":
    asyncio.run(test())
