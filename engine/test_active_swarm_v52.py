import asyncio
import logging
import sys
import os
from pathlib import Path

# 确保可以导入 engine 模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.agent_engine import AgentEngine
from engine.swarm import SwarmNetwork

# 配置日志 - 提高级别以观察心跳和数据包
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Coda.active_test")

def load_env():
    env_path = Path("d:/ai/workspace/.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                k, v = key.strip(), value.strip()
                os.environ[k] = v
        # 使用环境中定义模型
        model = os.getenv("DEFAULT_MODEL_NAME", "gemini-2.0-flash-exp")
        logger.info(f"Loaded environment. Using model: {model}")

async def run_active_verification():
    load_env()
    working_dir = Path("d:/ai/workspace").absolute()
    test_file = working_dir / "physical_sync_test.txt"
    if test_file.exists(): test_file.unlink()
    
    # 1. 初始化物理共享网络
    swarm = SwarmNetwork(agent_id="test_orchestrator")
    await swarm.start_listening()
    
    # 2. 初始化真实 Agent 实例 (Active Agents)
    # 设置很短的迭代次数，仅用于同步验证
    coder = AgentEngine(
        working_dir=working_dir,
        agent_id="coder",
        swarm=swarm,
        max_iterations=2
    )
    
    verifier = AgentEngine(
        working_dir=working_dir,
        agent_id="verifier",
        swarm=swarm,
        max_iterations=2
    )
    
    # 3. 定义物理同步任务
    # Coder 负责写入，Verifier 负责在感知到变更后读取验证
    coder_goal = (
        "【物理同步任务 - 执行侧】:\n"
        "1. 使用 write_file 工具创建文件 'physical_sync_test.txt'。\n"
        "2. 内容必须包含独一无二的核心标记: 'Coda-V5.2-ACTIVE-SYNC-OK'。\n"
        "3. 完成后，确保你的认知包已广播到 Swarm 网络。"
    )
    
    verifier_goal = (
        "【物理同步任务 - 验证侧】:\n"
        "1. 监听 Swarm 网络中的变更通知。\n"
        "2. 一旦感知到 'physical_sync_test.txt' 的变更，立即使用 read_file 读取该文件。\n"
        "3. 检查是否存在标记 'Coda-V5.2-ACTIVE-SYNC-OK'。\n"
        "4. 如果存在，请在你的最终回复中明确阐述：'PHYSICAL VERIFICATION SUCCESS'。"
    )
    
    logger.info("🚀 Launching Active Multi-Agent Verification Loop...")
    
    try:
        # 并行执行
        results = await asyncio.gather(
            coder.run(coder_goal),
            verifier.run(verifier_goal)
        )
        
        logger.info("✅ Active Verification Loop Completed.")
        for i, res in enumerate(results):
            agent_name = "Coder" if i == 0 else "Verifier"
            logger.info(f"--- {agent_name} Final Output ---\n{res}\n")
            
    finally:
        # 清理
        await swarm.stop_listening()
        if test_file.exists():
            # 这里保留一会儿供人工检查，或者直接删除
            logger.info(f"Test file remains at: {test_file}")

if __name__ == "__main__":
    try:
        asyncio.run(run_active_verification())
    except KeyboardInterrupt:
        logger.info("Test aborted by user.")
    except Exception as e:
        logger.exception(f"Test failed with exception: {e}")
