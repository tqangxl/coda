"""
Coda V5.2 — Swarm Hierarchy & Command Warden (Phase 3)
实现指挥链审计、团队拓扑管理与上级指令优先权验证。
"""

from __future__ import annotations
import logging
import time
from typing import Dict, List, Optional, Set, Any, cast
from .base_types import SovereignIdentity, UniversalCognitivePacket
from .db import SurrealStore

logger = logging.getLogger("Coda.hierarchy")

class SwarmTeam:
    """
    团队拓扑管理器。
    维护团队成员、领袖与追随者的关系。
    """
    def __init__(self, team_id: str, leader_did: str):
        self.team_id = team_id
        self.leader_did = leader_did
        self.member_dids: Set[str] = {leader_did}
        self.sub_teams: List[SwarmTeam] = []

    def add_member(self, did: str) -> None:
        self.member_dids.add(did)
        logger.info(f"Team {self.team_id}: Member added {did}")

    def is_leader(self, did: str) -> bool:
        return did == self.leader_did

class CommandWarden:
    """
    指挥官审计机 (V5.2).
    增加持久化记录，支持跨团队指令审计轨迹追踪。
    """
    def __init__(self, store: Optional[SurrealStore] = None):
        self.teams: Dict[str, SwarmTeam] = {}
        self._store = store

    def set_store(self, store: SurrealStore) -> None:
        """设置持久化存储引擎。"""
        self._store = store
        logger.debug("📦 Persistence store attached to CommandWarden.")

    def register_team(self, team: SwarmTeam) -> None:
        self.teams[team.team_id] = team

    async def audit_command(self, packet: UniversalCognitivePacket, receiver_identity: SovereignIdentity) -> bool:
        """
        审计进站指令包 (V5.2 Enterprise Hardening).
        增加了基于 Rank (Priority) 的权限判定。
        """
        source = packet.source
        result = False
        reason = "Unknown"
        
        # 1. 基础校验：检查 DID 是否有效
        if not source.did:
            reason = "Missing source DID"
            result = False
        
        # 2. 层级校验 (Rank-Based)
        # Priority 1 是最高级，10 是最低级
        source_rank = source.priority or 10
        target_rank = receiver_identity.priority or 10
        
        if source_rank < target_rank:
            # 高级别指挥低级别
            reason = f"Rank Superior ({source_rank} < {target_rank})"
            result = True
        elif source_rank == target_rank and source.did != receiver_identity.did:
            # ── [V5.2] 同级别许可 (Broad Permission) ──
            # 在同一 Team 内允许 Peers 互相指令以支持冗余负载
            if source.team_id == receiver_identity.team_id:
                reason = "Peer in same team (Broad Perm)"
                result = True
            else:
                reason = "Cross-team peer command denied"
                result = False
        elif source.did == receiver_identity.did:
            # 自指令
            reason = "Self-loop instruction"
            result = True
        else:
            # 低级别尝试指挥高级别
            reason = f"Rank Insufficient ({source_rank} > {target_rank})"
            result = False

        # 3. 跨团队异常拦截 (可选覆盖)
        if result and source.team_id != receiver_identity.team_id:
            # 如果是跨团队，除非是全局指挥官，否则默认拦截
            if source.role_id != "coordinator":
                reason = "Unauthorized cross-team directive"
                result = False
        # 3. 持久化记录到数据库 (Audit Trail)
        if self._store and self._store.is_connected:
            try:
                record = {
                    "packet_id": packet.id,
                    "source_did": source.did,
                    "target_did": receiver_identity.did,
                    "objective": packet.objective,
                    "result": result,
                    "reason": reason,
                    "timestamp": time.time()
                }
                # 使用封装好的 create_record 方法
                await self._store.create_record("audit_trails", record)
            except Exception as e:
                logger.error(f"Failed to log audit trail: {e}")

        if result:
            logger.info(f"✅ Warden APPROVED: {reason} ({source.to_short_id()} -> {receiver_identity.to_short_id()})")
        else:
            logger.warning(f"🛡️ Warden REJECTED: {reason} ({source.did} -> {receiver_identity.did})")
            
        return result

# 全局指挥单例
warden = CommandWarden()
