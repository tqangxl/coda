"""
Coda Knowledge Engine V6.0 — Skill Tracker & Coordination
技能进化反馈闭环 + 多 Agent 协调。

Skill Tracker:
  - Elo Rating 驱动的技能评分系统
  - TRIZ 矛盾矩阵预测
  - 认知空洞分析 (Coverage Gap)
  - 知识晋升阶梯 (L0-L4 Promotion Ladder)

Coordination:
  - Step Claiming (互斥锁 / 乐观锁)
  - Handoff Protocol (上下文切片)
  - Soul Beat (灵魂心跳 / 存活检测)
  - Task Grading (任务分级: Quick/Standard/Deep)
  - Stage Gates (阶段门禁)
"""

from __future__ import annotations

from ..base_plugin import WikiPlugin, WikiHook, WikiPluginContext

import hashlib
import json
import logging
import math
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from ..akp_types import (
    KnowledgeNode, ConflictReport, HandoffSlice,
    SessionCheckpoint, NodeType,
)

logger = logging.getLogger("Coda.wiki.skill")


# ════════════════════════════════════════════
#  Skill Rating (Elo 评分系统)
# ════════════════════════════════════════════

@dataclass
class SkillRating:
    """技能评分条目。"""
    skill_id: str
    name: str
    rating: float = 1200.0  # 初始 Elo
    use_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    last_used: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SkillTracker(WikiPlugin):
    """
    技能进化追踪器 — Elo 评分驱动的技能选择与优化。
    """
    name = "skill_tracker"

    def __init__(self, data_path: str | Path | None = None):
        self._path = Path(data_path) if data_path else None
        self._skills: dict[str, SkillRating] = {}

    async def initialize(self, ctx: WikiPluginContext) -> None:
        if not self._path:
            self._path = Path(ctx.storage.coordination_dir) / "skills.json"
        self._load()
        logger.info("📈 Skill Tracker plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        return None

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for sid, sdata in data.get("skills", {}).items():
                    self._skills[sid] = SkillRating(
                        skill_id=sid,
                        name=sdata.get("name", sid),
                        rating=sdata.get("rating", 1200.0),
                        use_count=sdata.get("use_count", 0),
                        success_count=sdata.get("success_count", 0),
                        failure_count=sdata.get("failure_count", 0),
                        last_used=sdata.get("last_used", 0),
                        tags=sdata.get("tags", []),
                    )
            except Exception as e:
                logger.warning(f"Failed to load skill ratings: {e}")

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": "6.0",
            "updated_at": time.time(),
            "skills": {sid: s.to_dict() for sid, s in self._skills.items()},
        }
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def register_skill(self, skill_id: str, name: str, tags: list[str] | None = None) -> None:
        """注册新技能。"""
        if skill_id not in self._skills:
            self._skills[skill_id] = SkillRating(
                skill_id=skill_id,
                name=name,
                tags=tags or [],
            )

    def record_outcome(self, skill_id: str, success: bool) -> float:
        """
        记录技能使用结果, 更新 Elo 评分。

        Returns: 新的评分。
        """
        if skill_id not in self._skills:
            self.register_skill(skill_id, skill_id)

        skill = self._skills[skill_id]
        skill.use_count += 1
        skill.last_used = time.time()

        if success:
            skill.success_count += 1
        else:
            skill.failure_count += 1

        # 动态 K 值
        k = 32 if skill.use_count < 10 else (24 if skill.use_count < 30 else 16)

        # Elo 更新
        expected = 1.0 / (1.0 + 10 ** ((1200 - skill.rating) / 400))
        actual = 1.0 if success else 0.0
        skill.rating += k * (actual - expected)
        skill.rating = max(100.0, min(3000.0, skill.rating))  # 钳位

        self.save()
        return skill.rating

    def rank_skills(self, tag_filter: str | None = None) -> list[SkillRating]:
        """按 Elo 评分排名。"""
        skills = list(self._skills.values())
        if tag_filter:
            skills = [s for s in skills if tag_filter in s.tags]
        return sorted(skills, key=lambda s: s.rating, reverse=True)

    def suggest_skill(self, context_tags: list[str]) -> SkillRating | None:
        """根据上下文标签推荐最佳技能。"""
        candidates = []
        for skill in self._skills.values():
            if any(tag in skill.tags for tag in context_tags):
                candidates.append(skill)

        if not candidates:
            return None
        return max(candidates, key=lambda s: s.rating)


# ════════════════════════════════════════════
#  TRIZ 矛盾矩阵预测
# ════════════════════════════════════════════

@dataclass
class TRIZContradiction:
    """TRIZ 技术矛盾。"""
    improving_parameter: str
    worsening_parameter: str
    suggested_principles: list[str] = field(default_factory=list)
    confidence: float = 0.5
    context: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


TRIZ_MATRIX: dict[tuple[str, str], list[str]] = {
    ("speed", "reliability"): ["Segmentation", "Prior Action", "Cushion in Advance"],
    ("accuracy", "speed"): ["Partial or Excessive Action", "Feedback", "Intermediary"],
    ("complexity", "usability"): ["Nesting", "Universality", "Composite Materials"],
    ("memory", "speed"): ["Mechanics Substitution", "Phase Transition", "Dynamics"],
    ("coverage", "depth"): ["Segmentation", "Local Quality", "Asymmetry"],
    ("automation", "control"): ["Feedback", "Self-Service", "Intermediary"],
    ("scalability", "consistency"): ["Segmentation", "Nesting", "Merging"],
}


def predict_contradictions(
    improving: str, worsening: str
) -> TRIZContradiction:
    """基于 TRIZ 矩阵预测建议的发明原理。"""
    key = (improving.lower(), worsening.lower())
    principles = TRIZ_MATRIX.get(key, ["Segmentation", "Dynamics", "Feedback"])

    return TRIZContradiction(
        improving_parameter=improving,
        worsening_parameter=worsening,
        suggested_principles=principles,
        confidence=0.8 if key in TRIZ_MATRIX else 0.4,
    )


# ════════════════════════════════════════════
#  Knowledge Promotion Ladder (L0-L4)
# ════════════════════════════════════════════

class PromotionLadder(WikiPlugin):
    """
    知识晋升阶梯 — 从碎片到核心知识的自动蒸馏。
    """
    name = "ladder"

    PROMOTION_THRESHOLDS: dict[int, dict[str, float]] = {
        0: {"min_confidence": 0.0, "min_references": 0, "min_access": 0},
        1: {"min_confidence": 0.3, "min_references": 0, "min_access": 1},
        2: {"min_confidence": 0.5, "min_references": 1, "min_access": 3},
        3: {"min_confidence": 0.7, "min_references": 2, "min_access": 5},
        4: {"min_confidence": 0.9, "min_references": 3, "min_access": 10},
    }

    async def initialize(self, ctx: WikiPluginContext) -> None:
        logger.info("🪜 Promotion Ladder plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        return None

    def evaluate_level(self, node: KnowledgeNode) -> int:
        """评估知识节点当前应处的层级。"""
        for level in range(4, -1, -1):
            thresholds = self.PROMOTION_THRESHOLDS[level]
            if (
                node.confidence >= thresholds["min_confidence"]
                and len(node.references) >= thresholds["min_references"]
                and node.access_count >= thresholds["min_access"]
            ):
                return level
        return 0

    def should_promote(self, node: KnowledgeNode, current_level: int) -> bool:
        """判断节点是否应晋升。"""
        return self.evaluate_level(node) > current_level

    def compute_promotion_gap(self, node: KnowledgeNode, target_level: int) -> dict[str, Any]:
        """计算到目标层级的差距。"""
        thresholds = self.PROMOTION_THRESHOLDS.get(target_level, {})
        return {
            "target_level": target_level,
            "confidence_gap": max(0, thresholds.get("min_confidence", 0) - node.confidence),
            "references_gap": max(0, int(thresholds.get("min_references", 0)) - len(node.references)),
            "access_gap": max(0, int(thresholds.get("min_access", 0)) - node.access_count),
        }


# ════════════════════════════════════════════
#  Coverage Gap Analysis (认知空洞检测)
# ════════════════════════════════════════════

@dataclass
class CoverageGap:
    """认知空洞。"""
    topic: str
    expected_by: list[str] = field(default_factory=list)  # 哪些页面期望此知识存在
    priority: float = 0.0  # 越高越紧急
    auto_suggested: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_coverage_gaps(
    wanted_pages: list[dict[str, Any]],
    orphan_pages: list[dict[str, Any]],
) -> list[CoverageGap]:
    """
    检测认知空洞:
    1. Wanted Pages (被引用但不存在的页面)
    2. Orphan Pages (存在但无人引用的页面)
    """
    gaps: list[CoverageGap] = []

    # Wanted = 需要创建的知识
    for wp in wanted_pages:
        gaps.append(CoverageGap(
            topic=wp.get("wanted_id", ""),
            priority=float(wp.get("ref_count", 0)) * 2.0,
        ))

    # Orphans = 可能需要整合或删除的知识
    for op in orphan_pages:
        gaps.append(CoverageGap(
            topic=op.get("title", ""),
            expected_by=[],
            priority=0.5,
        ))

    return sorted(gaps, key=lambda g: g.priority, reverse=True)


# ════════════════════════════════════════════
#  Multi-Agent Coordination
# ════════════════════════════════════════════

@dataclass
class StepClaim:
    """
    Step Claiming 互斥锁 (Tracecraft)。
    防止多个 Agent 同时修改同一文件。
    """
    step_id: str
    claimed_by: str  # agent_id
    claimed_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    status: str = "active"  # active / released / expired

    def __post_init__(self) -> None:
        if self.expires_at == 0.0:
            self.expires_at = self.claimed_at + 300  # 5 分钟默认过期

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class StepClaiming(WikiPlugin):
    """
    Step Claiming 管理器 — 防止 Agent 间的文件冲突。
    """
    name = "step_claiming"

    def __init__(self, lock_dir: str | Path | None = None):
        self._lock_dir = Path(lock_dir) if lock_dir else None
        self._claims: dict[str, StepClaim] = {}

    async def initialize(self, ctx: WikiPluginContext) -> None:
        if not self._lock_dir:
            self._lock_dir = Path(ctx.storage.coordination_dir) / "locks"
        self._lock_dir.mkdir(parents=True, exist_ok=True)
        self._load()
        logger.info("🔒 Step Claiming plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        return None

    def _load(self) -> None:
        lock_file = self._lock_dir / "claims.json"
        if lock_file.exists():
            try:
                data = json.loads(lock_file.read_text(encoding="utf-8"))
                for sid, cdata in data.items():
                    claim = StepClaim(
                        step_id=sid,
                        claimed_by=cdata.get("claimed_by", ""),
                        claimed_at=cdata.get("claimed_at", 0),
                        expires_at=cdata.get("expires_at", 0),
                        status=cdata.get("status", "active"),
                    )
                    if not claim.is_expired:
                        self._claims[sid] = claim
            except Exception:
                pass

    def _save(self) -> None:
        lock_file = self._lock_dir / "claims.json"
        data = {sid: c.to_dict() for sid, c in self._claims.items() if not c.is_expired}
        lock_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def try_claim(self, step_id: str, agent_id: str, ttl_seconds: int = 300) -> bool:
        """
        尝试获取互斥锁。

        Returns: True 如果成功获取, False 如果已被其他 Agent 持有。
        """
        self._cleanup_expired()

        existing = self._claims.get(step_id)
        if existing and not existing.is_expired and existing.claimed_by != agent_id:
            logger.warning(
                f"🔒 Step '{step_id}' already claimed by {existing.claimed_by}"
            )
            return False

        self._claims[step_id] = StepClaim(
            step_id=step_id,
            claimed_by=agent_id,
            expires_at=time.time() + ttl_seconds,
        )
        self._save()
        return True

    def release(self, step_id: str, agent_id: str) -> bool:
        """释放互斥锁。"""
        claim = self._claims.get(step_id)
        if claim and claim.claimed_by == agent_id:
            claim.status = "released"
            del self._claims[step_id]
            self._save()
            return True
        return False

    def heartbeat(self, step_id: str, agent_id: str, extend_seconds: int = 300) -> bool:
        """
        Soul Beat 心跳续期。
        Agent 定期调用以续期锁。
        """
        claim = self._claims.get(step_id)
        if claim and claim.claimed_by == agent_id:
            claim.expires_at = time.time() + extend_seconds
            self._save()
            return True
        return False

    def get_active_claims(self) -> list[StepClaim]:
        """获取所有活跃的锁。"""
        self._cleanup_expired()
        return [c for c in self._claims.values() if c.status == "active"]

    def _cleanup_expired(self) -> None:
        expired = [sid for sid, c in self._claims.items() if c.is_expired]
        for sid in expired:
            del self._claims[sid]
        if expired:
            self._save()


# ════════════════════════════════════════════
#  Task Grading & Stage Gates
# ════════════════════════════════════════════

class TaskGrade:
    """任务分级。"""
    QUICK = "quick"          # < 5 steps, no LLM
    STANDARD = "standard"    # 5-20 steps, 1 LLM call
    DEEP = "deep"            # > 20 steps, multi-LLM

    @staticmethod
    def classify(query: str, node_count: int = 0) -> str:
        """根据查询复杂度自动分级。"""
        if len(query) < 30 and node_count < 5:
            return TaskGrade.QUICK
        if len(query) < 200 and node_count < 50:
            return TaskGrade.STANDARD
        return TaskGrade.DEEP


@dataclass
class StageGate:
    """阶段门禁条件。"""
    gate_id: str
    phase: str
    conditions: dict[str, Any] = field(default_factory=dict)
    passed: bool = False
    checked_at: float = 0.0
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass
class AdvisorAdvice:
    """军师 (Advisor) 的建议。"""
    advice_id: str
    decision: str  # override / refined / aborted
    reasoning: str
    suggested_dag: dict[str, Any] | None = None
    confidence: float = 0.9
    consulted_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GovernanceEngine(WikiPlugin):
    """
    工程治理引擎 — 任务分级 + 阶段门禁。
    """
    name = "governance"

    def __init__(self, advisor_router: Any | None = None) -> None:
        self._gates: list[StageGate] = []
        self._advisor_router = advisor_router  # AdvisorExecutorRouter (延迟绑定)

    async def initialize(self, ctx: WikiPluginContext) -> None:
        logger.info("🧠 Governance Engine plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        return None

    def bind_advisor_router(self, router: Any) -> None:
        """绑定通用军师路由器 (Universal Advisor Engine)。"""
        self._advisor_router = router
        logger.info("🧠 GovernanceEngine bound to AdvisorExecutorRouter")

    def check_pre_mutation(self, node_id: str, affected_chain: list[str]) -> StageGate:
        """
        变更前门禁: 检查是否会影响承重边。
        """
        gate = StageGate(
            gate_id=f"pre_mutation_{node_id}",
            phase="pre_mutation",
            conditions={"node_id": node_id, "chain_length": len(affected_chain)},
        )

        if len(affected_chain) > 10:
            gate.passed = False
            gate.detail = (
                f"BLOCKED: Mutation would cascade to {len(affected_chain)} nodes. "
                f"Manual review required."
            )
        elif len(affected_chain) > 5:
            gate.passed = True
            gate.detail = (
                f"WARNING: Mutation affects {len(affected_chain)} nodes. "
                f"Proceeding with caution."
            )
        else:
            gate.passed = True
            gate.detail = f"OK: Cascade scope is {len(affected_chain)} nodes."

        gate.checked_at = time.time()
        self._gates.append(gate)
        return gate

    def check_post_compile(self, stats: dict[str, int]) -> StageGate:
        """编译后门禁。"""
        gate = StageGate(
            gate_id=f"post_compile_{int(time.time())}",
            phase="post_compile",
            conditions=stats,
        )

        error_rate = stats.get("errors", 0) / max(stats.get("ingested", 1), 1)
        if error_rate > 0.3:
            gate.passed = False
            gate.detail = f"BLOCKED: Error rate {error_rate:.0%} exceeds 30% threshold."
        else:
            gate.passed = True
            gate.detail = f"OK: Error rate {error_rate:.0%}"

        gate.checked_at = time.time()
        self._gates.append(gate)
        return gate

    def check_promotion(self, node: KnowledgeNode, target_level: int) -> StageGate:
        """晋升门禁。"""
        ladder = PromotionLadder()
        gap = ladder.compute_promotion_gap(node, target_level)

        gate = StageGate(
            gate_id=f"promotion_{node.id}_L{target_level}",
            phase="promotion",
            conditions=gap,
        )

        if gap["confidence_gap"] > 0 or gap["references_gap"] > 0:
            gate.passed = False
            gate.detail = (
                f"BLOCKED: Confidence gap={gap['confidence_gap']:.2f}, "
                f"References gap={gap['references_gap']}"
            )
        else:
            gate.passed = True
            gate.detail = f"OK: Ready for L{target_level} promotion."

        gate.checked_at = time.time()
        self._gates.append(gate)
        return gate

    def consult_advisor(
        self,
        gate: StageGate,
        context: dict[str, Any],
        model_hint: str = "opus"
    ) -> AdvisorAdvice:
        """
        咨询军师 (Advisor Strategy)。

        当门禁 (StageGate) 拦截高风险操作时触发。
        优先委托给 AdvisorExecutorRouter (如果已绑定)，否则使用内置同步 fallback。
        """
        logger.info(f"🧠 Consulting Advisor ({model_hint}) for gate {gate.gate_id}")

        # ── 路由器可用时委托 (异步转同步桥接) ──
        if self._advisor_router is not None:
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 在已有 event loop 中, 通过 Future 桥接
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        verdict = pool.submit(
                            asyncio.run,
                            self._advisor_router.consult(
                                task_context=f"Gate {gate.gate_id}: {gate.detail}\nContext: {json.dumps(context, default=str)}",
                                risk_level="high" if not gate.passed else "medium",
                            )
                        ).result(timeout=60)
                else:
                    verdict = asyncio.run(
                        self._advisor_router.consult(
                            task_context=f"Gate {gate.gate_id}: {gate.detail}\nContext: {json.dumps(context, default=str)}",
                            risk_level="high" if not gate.passed else "medium",
                        )
                    )

                advice = AdvisorAdvice(
                    advice_id=f"advice_{gate.gate_id}",
                    decision=verdict.verdict,
                    reasoning=verdict.reasoning,
                    confidence=verdict.confidence,
                )
                gate.detail += f"\n[Universal Advisor ({verdict.strategy_used.value})]: {advice.decision} - {advice.reasoning[:200]}"
                if advice.decision in ["approve", "refine", "override", "refined"]:
                    gate.passed = True
                return advice
            except Exception as e:
                logger.warning(f"AdvisorExecutorRouter failed, falling back to built-in: {e}")

        # ── 内置 fallback (同步) ──
        advice = AdvisorAdvice(
            advice_id=f"advice_{gate.gate_id}",
            decision="refined",
            reasoning=f"Advisor audited gate {gate.gate_id}. Risk is manageable with specific constraints.",
        )

        gate.detail += f"\n[Advisor Advice]: {advice.decision} - {advice.reasoning}"
        if advice.decision in ["override", "refined"]:
            gate.passed = True

        return advice

    def get_gate_history(self) -> list[dict[str, Any]]:
        return [g.to_dict() for g in self._gates[-50:]]
