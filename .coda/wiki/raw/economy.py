"""
Coda V5.2 — Family Office Economy System (Phase 4)
实现共享配额账本、级联下拨算法与分布式成本审计。
"""

from __future__ import annotations
import logging
import time
from typing import Dict, List, Optional, Any, cast
from dataclasses import dataclass, field, asdict
from .base_types import TokenUsage, SovereignIdentity
from .db import SurrealStore

logger = logging.getLogger("Coda.economy")

@dataclass
class QuotaNode:
    """经济节点：可以是团队、岗位或具体实例。"""
    id: str
    limit_usd: float
    used_usd: float = 0.0
    children: Dict[str, QuotaNode] = field(default_factory=dict)

    def can_consume(self, amount: float, check_parents: bool = True) -> bool:
        # 1. 检查自身限制
        if (self.used_usd + amount) > self.limit_usd:
            return False
        return True

    def consume(self, amount: float) -> bool:
        self.used_usd += amount
        return True

class FamilyOfficeLedger:
    """
    家族办公室账本 (V5.2).
    管理全局配额并支持级联下拨与持久化审计。
    """
    def __init__(self, total_budget: float = 100.0, store: Optional[SurrealStore] = None):
        self._store = store
        self.root = QuotaNode(id="family_office", limit_usd=total_budget)
        # 初始化默认团队
        self.allocate_to_team("default_team", 10.0)

    def set_store(self, store: SurrealStore) -> None:
        """设置持久化存储引擎。"""
        self._store = store
        logger.debug("📦 Persistence store attached to FamilyOfficeLedger.")

    async def initialize(self) -> None:
        """从数据库同步配额状态，累加历史消耗。"""
        if self._store and self._store.is_connected:
            try:
                db = cast(Any, self._store._db)
                # 聚合每个 Team 的总消耗
                res = await db.query("SELECT team_id, math::sum(cost) as total_used FROM agent_ledger GROUP BY team_id")
                ledger_data = res[0]['result'] if res and 'result' in res[0] else []
                
                for entry in ledger_data:
                    team_id = entry.get("team_id")
                    used = entry.get("total_used", 0)
                    if team_id == "family_office":
                        self.root.used_usd = used
                    else:
                        node = self.root.children.setdefault(team_id, QuotaNode(id=team_id, limit_usd=10.0))
                        node.used_usd = used
                
                # 重新计算 Root 的总消耗 (如果是跨团队聚合)
                res_root = await db.query("SELECT math::sum(cost) as grand_total FROM agent_ledger")
                grand_total = res_root[0]['result'][0]['grand_total'] if res_root and res_root[0]['result'] else 0
                self.root.used_usd = grand_total
                
                logger.info(f"📊 Ledger initialized. Root total used: ${self.root.used_usd:.6f}")
            except Exception as e:
                logger.error(f"Failed to initialize ledger state: {e}")

    def allocate_to_team(self, team_id: str, amount: float) -> bool:
        """从根预算下拨给团队。"""
        team_node = self.root.children.setdefault(team_id, QuotaNode(id=team_id, limit_usd=0))
        team_node.limit_usd += amount
        logger.info(f"💰 Allocated ${amount} to Team {team_id}")
        return True

    async def check_and_record(self, identity: SovereignIdentity, cost: float) -> bool:
        """
        审计并记录成本。
        执行级联检查 (Cascade Algorithm): Team -> FamilyOffice.
        """
        # 1. 确保团队存在
        team_node = self.root.children.get(identity.team_id)
        if not team_node:
            # 自动开户逻辑
            self.allocate_to_team(identity.team_id, 10.0) # 默认给 10 刀阈值
            team_node = self.root.children.get(identity.team_id)
            if not team_node: return False
        
        # 2. 级联验证 (Cascade Validation)
        # 在多层级下，应递归向上检查 node.parent
        if not team_node.can_consume(cost) or not self.root.can_consume(cost):
            logger.error(f"❌ Budget exceeded for {identity.team_id}: cost=${cost:.6f}")
            return False
            
        # 3. 内存扣费
        team_node.consume(cost)
        self.root.consume(cost)
        
        # 4. 持久化记录到数据库 (Double-entry Ledger)
        if self._store and self._store.is_connected:
            try:
                from typing import Any
                db = cast(Any, self._store._db)
                record = {
                    "did": identity.did,
                    "team_id": identity.team_id,
                    "cost": cost,
                    "total_used": self.root.used_usd,
                    "timestamp": time.time()
                }
                await db.create("agent_ledger", record)
            except Exception as e:
                logger.error(f"Failed to persist ledger record: {e}")
        
        logger.debug(f"💸 Recorded ${cost:.6f} for {identity.to_short_id()}")
        return True

    def record_usage(self, usage: TokenUsage) -> None:
        """记录 Token 使用量 (内存级追踪)。"""
        logger.debug(f"📈 Engine Usage tracked: {usage.total_tokens} tokens")

# 全局经济账本单例
ledger = FamilyOfficeLedger()
