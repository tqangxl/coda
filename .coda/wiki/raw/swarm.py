"""
Coda V4.0 — Swarm Neural Network (Pillar 25 & 29)
分布式集群直连: 支持多个 Agent 通过加密通道协同作业。
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Callable, cast, override

from .base_types import (
    SwarmRole,
    SwarmPeer,
    SwarmMessage,
    SwarmNetworkProtocol,
    UniversalCognitivePacket,
    SovereignIdentity,
)
from .identity import registry
from .routing import MatrixBus

logger = logging.getLogger("Coda.swarm")


class SwarmNetwork(SwarmNetworkProtocol):
    """
    分布式集群直连协作 (Pillar 29)。

    支持:
    - P2P 直连: 点对点加密通信, 无需中心服务器
    - Permission Bridge: 多个 Agent 间共享授权签名
    - Coordinator 调度: 主控引擎分发任务, 工作节点并发执行

    安全:
    - 所有消息使用 HMAC-SHA256 签名
    - 基于共享密钥的身份验证 (未来可升级为 JWT)
    """

    def __init__(self, agent_id: str, role: SwarmRole = SwarmRole.COORDINATOR, secret: str = ""):
        self.agent_id = agent_id
        self.role = role
        self._secret = secret or "Coda-default-secret"
        self._peers: dict[str, SwarmPeer] = {}
        self._message_handlers: dict[str, Callable[..., Any]] = {}
        self._task_queue: asyncio.Queue[UniversalCognitivePacket | SwarmMessage] = asyncio.Queue()
        self._results: dict[str, Any] = {}
        self._packet_history: list[UniversalCognitivePacket] = [] # [V5.2] 认知包历史
        self._max_history = 100
        self._listening_task: asyncio.Task[Any] | None = None
        
        # ── MatrixBus 核心调度层 (Pillar: Matrix Management) ──
        self.matrix_bus = MatrixBus()
        
        # ── Aegis 认知防火墙状态 (Pillar 32) ──
        self._token_buckets: dict[str, dict[str, float]] = {} # {did: {'tokens': 100, 'last_update': time}}
        self._dedup_cache: set[str] = set() # {packet_id}
        self._cache_limit = 1000

    @property
    def results(self) -> dict[str, Any]:
        """[V5.2] 获取已处理的数据包/结果缓冲。"""
        return self._results

    async def start_listening(self) -> None:
        """[V5.2] 启动本地监听循环，模拟网络层的数据收发。"""
        if self._listening_task: return
        self._listening_task = asyncio.create_task(self._process_queue())
        logger.info(f"Swarm network listening started for {self.agent_id}")

    async def stop_listening(self) -> None:
        """[V5.2] 停止本地监听循环。"""
        if self._listening_task:
            self._listening_task.cancel()
            try:
                await self._listening_task
            except asyncio.CancelledError:
                pass
            self._listening_task = None
            logger.info(f"Swarm network listening stopped for {self.agent_id}")

    async def _process_queue(self) -> None:
        """处理发送队列并将其模拟路由到接收缓冲。"""
        while True:
            item = await self._task_queue.get()
            
            if isinstance(item, SwarmMessage):
                # 简单模拟 SwarmMessage 路由
                msg_id = f"msg_{int(time.time() * 1000)}_{item.sender_id}"
                self._results[f"{item.receiver_id}:{msg_id}"] = item.payload
                self._task_queue.task_done()
                continue
            
            packet = item
            # 0. 去重检查
            if packet.id in self._dedup_cache:
                self._task_queue.task_done()
                continue
            
            # 1. 认知防火墙 (Aegis Firewall - Token Bucket)
            if not self._check_firewall(packet):
                logger.warning(f"🛡️ Aegis RATE_LIMIT packet from {packet.source.did}")
                self._task_queue.task_done()
                continue

            # 记录到去重缓存
            self._dedup_cache.add(packet.id)
            if len(self._dedup_cache) > self._cache_limit:
                # 简单 LRU 清理
                self._dedup_cache.clear() 

            # 2. [V5.2] 认知包存档
            self._packet_history.append(packet)
            if len(self._packet_history) > self._max_history:
                self._packet_history.pop(0)
                
            # 3. Matrix 路由转换 (Any-cast / Targeted)
            targets = self.matrix_bus.resolve_targets(packet, self._peers)
            
            for target_did in targets:
                # 模拟发送
                msg_id = f"sync_{int(time.time() * 1000)}_{packet.source.did}"
                if target_did == "broadcast":
                    self._results[msg_id] = packet.to_dict()
                else:
                    self._results[f"{target_did}:{msg_id}"] = packet.to_dict()
            
            self._task_queue.task_done()



    def _check_firewall(self, packet: UniversalCognitivePacket) -> bool:
        """
        Token Bucket 认知限流 (Aegis Firewall).
        每位 DID 拥有独立令牌桶，防止流量攻击。
        """
        now = time.time()
        source_did = packet.source.did
        bucket = self._token_buckets.setdefault(source_did, {"tokens": 100.0, "last_update": now})
        
        # 填充令牌 (速率: 每秒 2 个令牌，桶容量 100)
        elapsed = now - bucket["last_update"]
        bucket["tokens"] = min(100.0, bucket["tokens"] + elapsed * 2.0)
        bucket["last_update"] = now
        
        # 消耗令牌 (每个包根据重要性消耗不同权重)
        cost = 1.0 + (packet.importance / 10.0)
        if bucket["tokens"] >= cost:
            bucket["tokens"] -= cost
            return True
            
        return False

    # ══════════════════════════════════════
    #  节点管理
    # ══════════════════════════════════════

    def register_peer(self, peer: SwarmPeer) -> None:
        """注册一个对等节点。"""
        self._peers[peer.peer_id] = peer
        logger.info(f"Peer registered: {peer.peer_id} ({peer.role.value})")

    def remove_peer(self, peer_id: str) -> None:
        """移除一个对等节点。"""
        self._peers.pop(peer_id, None)

    @override
    def get_active_workers(self) -> list[SwarmPeer]:
        """获取所有活跃的工作节点。"""
        now = time.time()
        return [
            p for p in self._peers.values()
            if p.role == SwarmRole.WORKER and p.connected and (now - p.last_heartbeat) < 60
        ]

    # ══════════════════════════════════════
    #  消息签名与验证 (加密通信)
    # ══════════════════════════════════════

    def sign_message(self, msg: SwarmMessage) -> SwarmMessage:
        """使用 HMAC-SHA256 对消息进行签名。"""
        payload_str = json.dumps(msg.payload, sort_keys=True)
        raw = f"{msg.sender_id}:{msg.receiver_id}:{msg.msg_type}:{payload_str}:{msg.timestamp}"
        msg.signature = hmac.new(
            self._secret.encode(), raw.encode(), hashlib.sha256
        ).hexdigest()
        return msg

    def verify_message(self, msg: SwarmMessage) -> bool:
        """验证消息的 HMAC 签名。"""
        payload_str = json.dumps(msg.payload, sort_keys=True)
        raw = f"{msg.sender_id}:{msg.receiver_id}:{msg.msg_type}:{payload_str}:{msg.timestamp}"
        expected = hmac.new(
            self._secret.encode(), raw.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(msg.signature, expected)

    # ══════════════════════════════════════
    #  任务分发 (Coordinator 模式)
    # ══════════════════════════════════════

    @override
    async def dispatch_task(self, objective: str, instruction: str, target: str = "any:worker") -> str:
        """
        [V5.2] 使用 MatrixBus 分发任务给工作节点。
        """
        packet = UniversalCognitivePacket(
            source=registry.get_identity(self.agent_id) or SovereignIdentity(instance_id=self.agent_id),
            objective=objective,
            instruction=instruction,
            target=target
        )
        # 签名并发送
        packet.signature = registry.sign_packet(packet)
        await self._task_queue.put(packet)
        logger.info(f"Task dispatched via MatrixBus: {objective} -> {target}")
        return packet.id

    @override
    async def collect_result(self, task_id: str, timeout: float = 300.0) -> dict[str, Any] | None:
        """等待并收集任务结果。"""
        start = time.time()
        while time.time() - start < timeout:
            # 检查是否有发回给我的结果包
            res_key = f"{self.agent_id}:sync_"
            for key in list(self._results.keys()):
                if key.startswith(res_key) and self._results[key].get("id") == task_id:
                    result = self._results.pop(key)
                    return result
            await asyncio.sleep(0.5)
        return None

    @override
    async def broadcast_packet(self, packet: UniversalCognitivePacket) -> None:
        """
        [V5.2] 统一广播接口：直接发送认知包到 MatrixBus。
        """
        await self._task_queue.put(packet)
        logger.debug(f"Packet queued for broadcast: {packet.id}")

    async def broadcast_event(self, objective: str, instruction: str, payload: dict[str, Any]) -> None:
        """
        [V5.2 Legacy Wrapper] 向全集群广播认知包。
        """
        packet = UniversalCognitivePacket(
            source=registry.get_identity(self.agent_id) or SovereignIdentity(instance_id=self.agent_id),
            objective=objective,
            instruction=instruction,
            target="all",
            domain_payload=payload
        )
        packet.signature = registry.sign_packet(packet)
        await self.broadcast_packet(packet)

    # ══════════════════════════════════════
    #  Permission Bridge (权限共享)
    # ══════════════════════════════════════

    def grant_permission(self, peer_id: str, permissions: list[str]) -> SwarmMessage:
        """
        向指定节点授予权限 (Permission Bridge)。
        """
        msg = SwarmMessage(
            sender_id=self.agent_id,
            receiver_id=peer_id,
            msg_type="permission_grant",
            payload={"permissions": permissions, "expires_at": time.time() + 3600},
        )
        return self.sign_message(msg)

    # ══════════════════════════════════════
    #  Handoff Protocol (任务移交)
    # ══════════════════════════════════════

    async def handoff(self, target_agent_id: str, task_context: dict[str, Any]) -> str:
        """
        Pillar 25: 跨 Agent 移交任务 (Handoff)。
        """
        handoff_id = f"handoff_{int(time.time() * 1000)}"
        msg = SwarmMessage(
            sender_id=self.agent_id,
            receiver_id=target_agent_id,
            msg_type="handoff",
            payload={
                "handoff_id": handoff_id,
                "context": task_context,
                "timestamp": time.time(),
            },
        )
        msg = self.sign_message(msg)
        
        await self._task_queue.put(msg)
        logger.info(f"Handoff initiated: {handoff_id} -> {target_agent_id}")
        return handoff_id

    async def receive_handoff(self, msg: SwarmMessage) -> dict[str, Any] | None:
        """接收并处理任务移交。"""
        if msg.msg_type != "handoff":
            return None
        
        if not self.verify_message(msg):
            logger.warning(f"Failed to verify handoff signature from {msg.sender_id}")
            return None
        
        handoff_data = msg.payload
        logger.info(f"Handoff received from {msg.sender_id}: {handoff_data.get('handoff_id')}")
        return cast("dict[str, Any] | None", handoff_data.get("context"))

    # ══════════════════════════════════════
    #  心跳
    # ══════════════════════════════════════

    def create_heartbeat(self) -> SwarmMessage:
        """创建心跳消息。"""
        msg = SwarmMessage(
            sender_id=self.agent_id,
            receiver_id="broadcast",
            msg_type="heartbeat",
            payload={"role": self.role.value, "status": "alive"},
        )
        return self.sign_message(msg)

    def process_heartbeat(self, msg: SwarmMessage) -> None:
        """处理收到的心跳。"""
        if msg.sender_id in self._peers:
            self._peers[msg.sender_id].last_heartbeat = time.time()
            self._peers[msg.sender_id].connected = True



from typing import cast
