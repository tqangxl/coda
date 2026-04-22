"""
Coda V5.2 — MatrixBus Routing Controller (Phase 1)
实现具备断路器隔离、加权分发与遥测能力的智能路由总线。
"""

from __future__ import annotations
import time
import random
import logging
from typing import Any
from enum import Enum
from dataclasses import dataclass
from .base_types import SwarmPeer, UniversalCognitivePacket

logger = logging.getLogger("Coda.routing")

class CircuitState(Enum):
    CLOSED = "closed"   # 健康，允许流量
    OPEN = "open"       # 熔断，拒绝流量
    HALF_OPEN = "half_open" # 恢复中，尝试少量流量

@dataclass
class CircuitBreaker:
    """断路器状态机。"""
    failure_threshold: int = 3
    recovery_timeout: float = 30.0
    
    failures: int = 0
    state: CircuitState = CircuitState.CLOSED
    last_failure_at: float = 0.0

    def record_failure(self):
        self.failures += 1
        self.last_failure_at = time.time()
        if self.failures >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(f"🚨 CircuitBreaker: State changed to OPEN (failures: {self.failures})")

    def record_success(self):
        self.failures = 0
        self.state = CircuitState.CLOSED

    def can_route(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        
        # 检查是否可以进入 HALF_OPEN
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_at > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                logger.info("🧪 CircuitBreaker: State changed to HALF_OPEN")
                return True
        
        return self.state == CircuitState.HALF_OPEN

class MatrixBus:
    """
    Coda MatrixBus 核心路由总线。
    支持弹性路由、加权负载均衡与故障发现。
    """
    def __init__(self):
        self._circuits: dict[str, CircuitBreaker] = {}
        # 路由统计
        self._stats: dict[str, dict[str, Any]] = {}

    def _get_circuit(self, peer_id: str) -> CircuitBreaker:
        if peer_id not in self._circuits:
            self._circuits[peer_id] = CircuitBreaker()
        return self._circuits[peer_id]

    def resolve_targets(self, packet: UniversalCognitivePacket, peers: dict[str, SwarmPeer]) -> list[str]:
        """
        根据路由字符串和对等节点列表解析最终 DID 列表。
        """
        target = packet.target
        candidates: list[SwarmPeer] = []
        
        # 1. 广播策略
        if target == "all":
            return ["broadcast"]
            
        # 2. 解析目标
        if target.startswith("role:"):
            role = target.split(":")[1]
            candidates = [p for p in peers.values() if p.identity.role_id == role]
        elif target.startswith("team:"):
            team = target.split(":")[1]
            candidates = [p for p in peers.values() if p.identity.team_id == team]
        elif target.startswith("any:"):
            role = target.split(":")[1]
            candidates = [p for p in peers.values() if p.identity.role_id == role]
            if candidates:
                # 触发加权负载均衡
                selected = self._load_balance(candidates)
                candidates = [selected] if selected else []
        else:
            # 直接 DID
            if target in peers:
                candidates = [peers[target]]
            else:
                # 盲投模式
                return [target]

        # 2. 断路器过滤与自动备份 (Circuit Breaker & Fallback)
        reachable = []
        for p in candidates:
            circuit = self._get_circuit(p.peer_id)
            if p.connected and circuit.can_route():
                reachable.append(p.peer_id)
            else:
                # ── [V5.2] 触发专家自动备份 (Expert Fallback) ──
                # 如果当前节点不可用，尝试寻找同角色的其他健康节点
                role = p.identity.role_id
                logger.warning(f"🚧 MatrixBus: {p.peer_id} is unavailable. Seeking alternate {role}...")
                
                alternates = [
                    alt for alt in peers.values()
                    if alt.identity.role_id == role 
                    and alt.peer_id != p.peer_id
                    and alt.connected
                    and self._get_circuit(alt.peer_id).can_route()
                ]
                
                if alternates:
                    backup = self._load_balance(alternates)
                    if backup:
                        logger.info(f"🔄 MatrixBus: Rerouted from {p.peer_id} to {backup.peer_id} ({role})")
                        reachable.append(backup.peer_id)
                else:
                    logger.error(f"❌ MatrixBus: No backup nodes found for role:{role}")

        return reachable

    def _load_balance(self, candidates: list[SwarmPeer]) -> SwarmPeer | None:
        """
        加权负载均衡算法。
        基于 identity.priority 进行倒数加权 (优先级 1 权重最高)。
        """
        if not candidates: return None
        
        # 过滤处于 OPEN 状态的候选者 (熔断保护)
        alive_candidates = [
            c for c in candidates 
            if self._get_circuit(c.peer_id).can_route() and c.connected
        ]
        
        if not alive_candidates: 
            logger.warning("⚠️ MatrixBus: All candidates are circuit-broken or offline.")
            return None
        
        # 计算权重：10 / priority 
        # 使用 max(0.1, ...) 避免除零，并保证最低权重
        weights = [max(0.1, 10.0 / float(c.identity.priority or 10)) for c in alive_candidates]
        
        # 随机加权选择
        return random.choices(alive_candidates, weights=weights, k=1)[0]

    def report_success(self, peer_id: str):
        self._get_circuit(peer_id).record_success()

    def report_failure(self, peer_id: str):
        self._get_circuit(peer_id).record_failure()

