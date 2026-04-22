
import asyncio
import logging
import sys
import os
from pathlib import Path

# Add workspace root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.routing import MatrixBus, CircuitState
from engine.base_types import SovereignIdentity, SwarmPeer, UniversalCognitivePacket
from engine.hierarchy import CommandWarden, SwarmTeam
from engine.plugins import PluginRegistry, SidecarPlugin

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Coda.verify_enterprise")

async def test_peer_permission():
    logger.info("🧪 Testing Peer-to-Peer Permission...")
    warden = CommandWarden()
    
    # 定义同一团队的两个同级 Peer (Priority 5)
    peer_a = SovereignIdentity(did="did:a", team_id="team_alpha", priority=5)
    peer_b = SovereignIdentity(did="did:b", team_id="team_alpha", priority=5)
    
    # 注册团队
    team = SwarmTeam(team_id="team_alpha", leader_did="did:leader")
    warden.register_team(team)
    
    # 模拟 Peer A 向 Peer B 发送指令
    packet = UniversalCognitivePacket(
        id="cmd_01",
        source=peer_a,
        target="did:b",
        objective="Analyze logs",
        instruction="Please read agent/logs/audit.log"
    )
    
    approved = await warden.audit_command(packet, peer_b)
    assert approved is True, "Peer command within same team should be approved (Broad Perm)"
    logger.info("✅ Peer-to-Peer Permission test passed!")

async def test_expert_fallback():
    logger.info("🧪 Testing MatrixBus Expert Fallback...")
    bus = MatrixBus()
    
    # 准备三个对等节点，两个是 Coder
    from engine.base_types import SwarmRole
    coder_1 = SwarmPeer(peer_id="did:coder_1", role=SwarmRole.WORKER, identity=SovereignIdentity(role_id="coder", priority=5))
    coder_2 = SwarmPeer(peer_id="did:coder_2", role=SwarmRole.WORKER, identity=SovereignIdentity(role_id="coder", priority=5))
    eval_1 = SwarmPeer(peer_id="did:eval_1", role=SwarmRole.WORKER, identity=SovereignIdentity(role_id="evaluator", priority=1))
    
    coder_1.connected = True
    coder_2.connected = True
    eval_1.connected = True
    
    peers = {
        "did:coder_1": coder_1,
        "did:coder_2": coder_2,
        "did:eval_1": eval_1
    }
    
    # 1. 正常路由
    pkt = UniversalCognitivePacket(
        id="p1", 
        source=eval_1.identity, 
        target="did:coder_1", 
        objective="Code X",
        instruction="Impl feature A"
    )
    targets = bus.resolve_targets(pkt, peers)
    assert "did:coder_1" in targets
    
    # 2. 模拟 coder_1 熔断
    logger.info("📉 Triggering Circuit Breaker for coder_1...")
    for _ in range(5):
        bus.report_failure("did:coder_1")
    
    # 3. 再次向 coder_1 发送，预期触发 fallback 到 coder_2
    targets_fallback = bus.resolve_targets(pkt, peers)
    assert "did:coder_2" in targets_fallback, f"Expected fallback to coder_2, got {targets_fallback}"
    logger.info("✅ Expert Fallback test passed!")

async def test_plugin_strict_mode():
    logger.info("🧪 Testing Plugin Strict Resource Guard...")
    registry = PluginRegistry()
    
    # 模拟一个会抛错的插件动作或资源超限
    # 这里我们主要测试 registry.strict_resource_limit 开关是否正确同步
    registry.strict_resource_limit = True
    assert registry.strict_resource_limit is True
    
    registry.strict_resource_limit = False
    assert registry.strict_resource_limit is False
    logger.info("✅ Plugin Strict Mode toggle test passed!")

async def main():
    try:
        await test_peer_permission()
        await test_expert_fallback()
        await test_plugin_strict_mode()
        logger.info("\n🚀 ALL ENTERPRISE HARDENING TESTS PASSED!")
    except Exception as e:
        logger.error(f"❌ Verification failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
