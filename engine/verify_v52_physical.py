import asyncio
import json
import logging
import os
import shutil
import time
from pathlib import Path

# 设置路径上下文
WORKSPACE = Path("d:/ai/workspace")
os.chdir(WORKSPACE)

from engine.transport import LocalBridge
from engine.knowledge_plugin import WikiPlugin
from engine.base_types import UniversalCognitivePacket, SwarmPeer, SwarmRole, SovereignIdentity
from engine.identity import registry

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("verify_v52")

async def verify_local_bridge():
    logger.info("Step 1: Verifying LocalBridge Hardening (Physical IPC)")
    agent_id = "test_bridge_agent"
    
    # 明确指定 bridge_dir 以确保验证一致性
    bridge_dir = WORKSPACE / "agents" / ".bridge"
    bridge = LocalBridge(agent_id=agent_id, bridge_dir=bridge_dir)
    
    # 清理旧数据
    inbox_path = bridge_dir / f"{agent_id}.inbox"
    if inbox_path.exists():
        inbox_path.unlink()
    
    # 构建测试包
    packet = {
        "id": f"test_{int(time.time())}",
        "source": "witness",
        "payload": "Physical handshake test"
    }
    
    # 模拟外部写入 .inbox (JSONL 格式)
    bridge_dir.mkdir(parents=True, exist_ok=True)
    with open(inbox_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(packet) + "\n")
    
    # 读取并验证
    received = bridge.receive()
    if received and received[0]["id"] == packet["id"]:
        logger.info("✅ LocalBridge: Physical IPC verified (JSONL read success)")
    else:
        logger.error(f"❌ LocalBridge: Physical IPC verification failed. Received: {received}")

async def verify_wiki_plugin():
    logger.info("Step 2: Verifying WikiPlugin Hardening (Local Knowledge)")
    wiki = WikiPlugin()
    
    # 创建临时知识文件
    test_kb = WORKSPACE / "agents" / "tester" / "SOUL.md"
    test_kb.parent.mkdir(parents=True, exist_ok=True)
    test_kb.write_text("# Knowledge Test\nThe secret code is AG-77-SYNC.", encoding="utf-8")
    
    # 查询关键字
    results = await wiki.query("secret code")
    found = any("AG-77-SYNC" in str(r) for r in results)
    if found:
        logger.info("✅ WikiPlugin: Local knowledge retrieval verified")
    else:
        logger.error(f"❌ WikiPlugin: Verification failed. Result: {results}")

async def verify_logging_consolidation():
    logger.info("Step 3: Verifying Log Aggregation Consolidation")
    
    # 我们直接模拟 AgentEngine 的日志记录行为
    # 注意：为了避免实例化整个 AgentEngine (需要 SurrealDB)，我们直接测试 SwarmNetwork 触发的逻辑
    # 由于我们现在将日志责任移交给了 AgentEngine，我们在 verify 脚本中模拟该行为
    
    agent_id = "test_logger_agent"
    log_dir = WORKSPACE / "agents" / agent_id / "logs"
    if log_dir.exists():
        shutil.rmtree(log_dir)
    
    # 模拟 Packet
    packet = UniversalCognitivePacket(
        source=SovereignIdentity(instance_id="witness"),
        objective="Verification Test",
        instruction="Log aggregation test instruction"
    )
    
    # 模拟 AgentEngine 的 _write_comm_log 逻辑
    central_log = log_dir / "communication.md"
    central_log.parent.mkdir(parents=True, exist_ok=True)
    
    # 直接导入更新后的 AgentEngine 类并执行
    from engine.agent_engine import AgentEngine
    try:
        # 我们创建一个 Mock Engine
        engine = AgentEngine(agent_id=agent_id, working_dir=str(WORKSPACE))
        # 绕过 initialize 里的 DB 连接
        # 我们只测试 _write_comm_log
        engine._write_comm_log(packet, direction="OUT")
        
        if central_log.exists():
            content = central_log.read_text(encoding="utf-8")
            if "| OUT |" in content and "Log aggregation" in content:
                logger.info("✅ Log Aggregation: Consolidated communication.md verified")
            else:
                logger.error("❌ Log Aggregation: Log format incorrect")
        else:
            logger.error("❌ Log Aggregation: central communication.md not created")
    except Exception as e:
        logger.error(f"❌ Log Aggregation verification encountered error: {e}")

async def main():
    try:
        await verify_local_bridge()
        await verify_wiki_plugin()
        await verify_logging_consolidation()
        logger.info("--- ALL V5.2 HARDENING VERIFICATIONS COMPLETE ---")
    except Exception as e:
        logger.error(f"FATAL: Verification suite failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
