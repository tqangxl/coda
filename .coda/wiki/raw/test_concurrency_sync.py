import asyncio
import os
import sys
import json
from pathlib import Path
from typing import Any, Mapping

# 调整路径以导入 engine 模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.tool_executor import ToolExecutor
from engine.progress_monitor import ProgressMonitor
from engine.base_types import UniversalCognitivePacket

class MockSwarm:
    def __init__(self):
        self._results = {}
        self.broadcast_count = 0
    
    async def broadcast_event(self, msg_type: str, payload: dict[str, Any]):
        self.broadcast_count += 1
        # 存入结果缓冲以模拟正在分发的消息
        msg_id = f"sync_{self.broadcast_count}"
        self._results[msg_id] = {
            "msg_type": msg_type,
            "sender_id": "other_agent",
            "payload": payload
        }
        print(f"DEBUG: Swarm Broadcast event emitted: {msg_type}")

async def test_file_locking():
    print("\n--- Test 1: File Locking (Atomic Writing) ---")
    executor = ToolExecutor(working_dir=".")
    test_file = Path("concurrency_test.txt")
    if test_file.exists(): test_file.unlink()
    
    async def slow_write(content: str, delay: float):
        # 模拟一个涉及文件锁的操作
        async with await executor._get_file_lock(test_file):
            print(f"Lock acquired for: {content}")
            await asyncio.sleep(delay)
            test_file.write_text(content)
            print(f"Write finished for: {content}")

    # 同时发起两个写请求
    # 第一个写1s，第二个应在第一个完成后才开始
    start_time = asyncio.get_event_loop().time()
    await asyncio.gather(
        slow_write("Content A", 0.5),
        slow_write("Content B", 0.1)
    )
    end_time = asyncio.get_event_loop().time()
    
    print(f"Total time: {end_time - start_time:.2f}s (Expected > 0.6s if serial)")
    final_content = test_file.read_text()
    print(f"Final content: {final_content}")
    
    if test_file.exists(): test_file.unlink()

async def test_line_perception():
    print("\n--- Test 2: Line-Level Perception ---")
    monitor = ProgressMonitor()
    old_content = "line1\nline2\nline3\nline4\n"
    new_content = "line1\nline2_modified\nline3\nline4_new\nline5\n"
    
    delta = monitor.compute_line_delta("test.py", old_content, new_content)
    print(f"Computed Local Delta: {json.dumps(delta, indent=2)}")
    
    if "2,1" in str(delta["ranges"]) or "4,2" in str(delta["ranges"]):
        print("SUCCESS: Accurate line ranges detected.")
    else:
        print("WARNING: Line detection might be imprecise.")

async def test_synchronization():
    print("\n--- Test 3: Multi-Agent Sync (Mocked) ---")
    # 这里的测试逻辑模拟 AgentEngine._sync_foreign_observations 的行为
    swarm = MockSwarm()
    
    # 模拟外部 Agent A 发出的广播
    from engine.base_types import SovereignIdentity
    packet = UniversalCognitivePacket(
        source=SovereignIdentity(instance_id="Agent-A"),
        objective="Refactor Auth",
        instruction="Modified auth.py lines",
        physical_delta={"path": "auth.py", "ranges": ["+10,2"], "summary": "Fixed leak"}
    )
    await swarm.broadcast_event("sync_event", packet.to_dict())
    
    # 模拟接收端 Agent B 的感知过程
    messages = []
    for msg_id, msg_data in swarm._results.items():
        if msg_data.get("msg_type") == "sync_event":
            payload = msg_data.get("payload", {})
            delta = payload.get("physical_delta", {})
            notice = f"[Perception] {msg_data['sender_id']} modified {delta.get('path')} (Objective: {payload.get('objective')})"
            messages.append(notice)
            print(f"Agent-B perceived: {notice}")
    
    if len(messages) > 0:
        print("SUCCESS: Foreign change perceived perfectly.")

if __name__ == "__main__":
    asyncio.run(test_file_locking())
    asyncio.run(test_line_perception())
    asyncio.run(test_synchronization())
