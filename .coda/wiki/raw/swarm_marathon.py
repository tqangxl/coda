import asyncio
import logging
import sys
import os
from pathlib import Path

# 确保可以导入 engine 模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.agent_engine import AgentEngine
from engine.swarm import SwarmNetwork

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Coda.marathon")

def load_env():
    env_path = Path("d:/ai/workspace/.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                k, v = key.strip(), value.strip()
                os.environ[k] = v
                # 映射到标准代理变量
                if k == "GEMINI_PROXY":
                    os.environ["HTTP_PROXY"] = v
                    os.environ["HTTPS_PROXY"] = v
        logger.info("Loaded environment from .env (including proxy mappings)")

async def run_marathon():
    load_env()
    working_dir = Path("d:/ai/workspace").absolute()
    
    # ── 1. 初始化共享集群网络 ──
    # 在这个实战场景中，我们模拟同一个进程内的 P2P
    swarm = SwarmNetwork(agent_id="marathon_orchestrator")
    await swarm.start_listening()
    
    # ── 2. 初始化核心角色 ──
    # Coder: 负责代码优化
    coder = AgentEngine(
        working_dir=working_dir,
        agent_id="coder",
        swarm=swarm,
        max_iterations=5  # 实战前 5 步
    )
    
    # Verifier: 负责测试与验证
    verifier = AgentEngine(
        working_dir=working_dir,
        agent_id="verifier",
        swarm=swarm,
        max_iterations=5
    )
    
    # ── 3. 为集群设定共同目标 ──
    goal = (
        "【集群协同任务】:\n"
        "1. Coder: 请优化 'engine/utils/token_audit.py'。你需要为正则模式增加缓存，"
        "并为 calculate_real_compute 函数引入 functools.lru_cache 以提升审计性能。\n"
        "2. Verifier: 请监听 Coder 的变更广播。一旦发现代码改动，请立即在 'engine/tests/test_token_audit.py' "
        "中编写配套测试用例，并在沙箱中执行验证，确保优化没有破坏原有逻辑。"
    )
    
    logger.info("🔥 Starting Swarm Marathon: Coder & Verifier are online.")
    
    # ── 4. 并行驱动集群 ──
    # 两者共享物理视图，并通过 UMDCS 协议同步认知
    await asyncio.gather(
        coder.run(goal),
        verifier.run(goal)
    )
    
    logger.info("🏁 Swarm Marathon finished its initial run.")

if __name__ == "__main__":
    try:
        asyncio.run(run_marathon())
    except KeyboardInterrupt:
        logger.info("Marathon interrupted by user.")
    except Exception as e:
        logger.error(f"Marathon crashed: {e}")
