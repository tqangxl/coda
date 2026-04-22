"""
Coda Knowledge Engine V7.2 — Dream Cycle (Autonomous Cognitive Metabolism)
50x 进阶认知代谢引擎: 四阶段睡眠循环 + 真实认知物理学 + LLM 合成 + 拓扑智能。

Phase 1 (LIGHT):  Epistemic Physics — 激活衰减 + 复利增值
Phase 2 (DEEP):   Structural Analysis — 孤岛检测 + 脆弱性热点 + 结构洞
Phase 3 (REM):    LLM Synthesis — 多对桥接 + 矛盾调解 + 隐式层次发现
Phase 4 (WAKE):   Pruning & Archival — 安全剪枝 + 冷存储迁移 + 审计
"""

from __future__ import annotations
import logging
import time
import math
import asyncio
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional
from enum import Enum

from ..base_plugin import WikiPlugin, WikiHook, WikiPluginContext

logger = logging.getLogger("Coda.wiki.dream_cycle")


# ════════════════════════════════════════
#  Data Models
# ════════════════════════════════════════

class DreamPhase(str, Enum):
    LIGHT = "light"
    DEEP  = "deep"
    REM   = "rem"
    WAKE  = "wake"

@dataclass
class DreamAction:
    action_type: str        # decay | boost | synthesize | archive | bridge | reconcile | orphan_reclaim
    target_nodes: list[str] = field(default_factory=list)
    rationale: str = ""
    confidence: float = 1.0

@dataclass
class PhaseReport:
    phase: DreamPhase
    duration: float = 0.0
    actions: list[DreamAction] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def action_count(self) -> int:
        return len(self.actions)

@dataclass
class FragilityAlert:
    node_id: str
    title: str = ""
    fan_in: int = 0
    confidence: float = 0.0
    severity: str = "warning"

@dataclass
class KnowledgeHealthReport:
    total_nodes: int = 0
    active_nodes: int = 0
    orphan_count: int = 0
    fragility_count: int = 0
    avg_confidence: float = 0.0
    avg_activation: float = 0.0
    freshness_pct: float = 0.0       # % nodes accessed in last 7 days
    coverage_pct: float = 0.0        # % nodes with >= 2 connections
    trend: str = "stable"            # growing | stable | decaying | fragmenting

@dataclass
class DreamReport:
    cycle_id: str = ""
    project_id: str = ""
    started_at: float = 0.0
    total_duration: float = 0.0
    phases: list[PhaseReport] = field(default_factory=list)
    nodes_decayed: int = 0
    nodes_boosted: int = 0
    synthesis_created: int = 0
    nodes_archived: int = 0
    orphans_found: int = 0
    fragility_hotspots: list[FragilityAlert] = field(default_factory=list)
    health: KnowledgeHealthReport = field(default_factory=KnowledgeHealthReport)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ════════════════════════════════════════
#  Decay Constants
# ════════════════════════════════════════

# Ebbinghaus forgetting curve time constants (hours)
_TAU = {
    "long_term":  720.0,   # 30 days — slow decay
    "summary":    336.0,   # 14 days
    "short_term":  48.0,   # 2 days — fast decay
    "working":      4.0,   # 4 hours — very fast
}
_BOOST_FACTOR = 0.15       # log(1 + access_count) multiplier
_CITATION_BONUS = 0.25     # per backlink
_PRUNE_THRESHOLD = 0.05    # activation below this → archive candidate
_ARCHIVE_BATCH = 20        # max nodes to archive per cycle
_SYNTHESIS_BATCH = 5       # max synthesis pairs per REM phase
_SIM_THRESHOLD = 0.72      # cosine similarity threshold for bridging


class DreamCycleService(WikiPlugin):
    """
    梦境循环服务 V7.2 — 四阶段自主认知代谢引擎。

    负责知识图谱的长效演化、自愈、剪枝与新知合成。
    通过 WikiHook.IDLE 自动触发，也可通过 API 手动触发。
    """
    name = "dream_cycle"

    def __init__(self):
        self._ctx: Optional[WikiPluginContext] = None
        self._is_running = False
        self._last_report: Optional[DreamReport] = None
        self._cycle_count = 0

    async def initialize(self, ctx: WikiPluginContext) -> None:
        self._ctx = ctx
        logger.info("🌙 Dream Cycle V7.2 initialized (4-Phase Cognitive Metabolism)")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        if hook == WikiHook.IDLE:
            asyncio.create_task(self.run_full_cycle())
        return None

    # ════════════════════════════════════════
    #  Public API
    # ════════════════════════════════════════

    async def run_full_cycle(self, project_id: str | None = None) -> DreamReport:
        """Execute a complete 4-phase dream cycle."""
        if self._is_running or not self._ctx:
            return DreamReport(cycle_id="skipped")

        self._is_running = True
        self._cycle_count += 1
        pid = project_id or self._ctx.project_id
        report = DreamReport(
            cycle_id=f"dream-{self._cycle_count}-{uuid.uuid4().hex[:6]}",
            project_id=pid,
            started_at=time.time(),
        )
        logger.info(f"🌙 Dream Cycle #{self._cycle_count}: Entering sleep for project '{pid}'...")

        try:
            # Phase 1: LIGHT — Epistemic Physics
            p1 = await self._phase_light(pid)
            report.phases.append(p1)
            report.nodes_decayed = sum(1 for a in p1.actions if a.action_type == "decay")
            report.nodes_boosted = sum(1 for a in p1.actions if a.action_type == "boost")

            # Phase 2: DEEP — Structural Analysis
            p2 = await self._phase_deep(pid)
            report.phases.append(p2)
            report.orphans_found = sum(1 for a in p2.actions if a.action_type == "orphan_detect")
            report.fragility_hotspots = [
                FragilityAlert(
                    node_id=a.target_nodes[0] if a.target_nodes else "",
                    title=a.rationale,
                    severity="critical" if a.confidence < 0.3 else "warning",
                )
                for a in p2.actions if a.action_type == "fragility_alert"
            ]

            # Phase 3: REM — LLM Synthesis
            p3 = await self._phase_rem(pid)
            report.phases.append(p3)
            report.synthesis_created = sum(1 for a in p3.actions if a.action_type == "synthesize")

            # Phase 4: WAKE — Pruning
            p4 = await self._phase_wake(pid)
            report.phases.append(p4)
            report.nodes_archived = sum(1 for a in p4.actions if a.action_type == "archive")

            # Health snapshot
            report.health = await self._compute_health(pid)

        except Exception as e:
            logger.error(f"Dream Cycle fatal error: {e}")
        finally:
            report.total_duration = time.time() - report.started_at
            self._last_report = report
            self._is_running = False
            logger.info(
                f"☀️ Dream Cycle #{self._cycle_count} complete: "
                f"{report.total_duration:.1f}s | "
                f"decayed={report.nodes_decayed} boosted={report.nodes_boosted} "
                f"synthesized={report.synthesis_created} archived={report.nodes_archived} "
                f"orphans={report.orphans_found} fragile={len(report.fragility_hotspots)}"
            )

        return report

    async def get_health(self, project_id: str | None = None) -> KnowledgeHealthReport:
        pid = project_id or (self._ctx.project_id if self._ctx else "default")
        return await self._compute_health(pid)

    @property
    def last_report(self) -> Optional[DreamReport]:
        return self._last_report

    # ════════════════════════════════════════
    #  Phase 1: LIGHT — Epistemic Physics
    # ════════════════════════════════════════

    async def _phase_light(self, pid: str) -> PhaseReport:
        report = PhaseReport(phase=DreamPhase.LIGHT)
        t0 = time.time()
        db = self._get_db()
        if not db:
            report.errors.append("No database connection")
            return report

        try:
            # 1a. Apply Ebbinghaus decay per memory_horizon
            for horizon, tau in _TAU.items():
                decay_factor = math.exp(-24.0 / tau)  # per-day step
                q = (
                    "UPDATE wiki_nodes SET activation_score = math::max(0.01, activation_score * $factor) "
                    "WHERE project_id = $pid AND memory_horizon = $horizon AND activation_score > 0.01"
                )
                res = await db._safe_query(q, {"pid": pid, "horizon": horizon, "factor": decay_factor})
                count = self._count_affected(res)
                if count > 0:
                    report.actions.append(DreamAction(
                        action_type="decay",
                        rationale=f"{horizon}: {count} nodes decayed (τ={tau}h, factor={decay_factor:.4f})",
                        confidence=1.0,
                    ))

            # 1b. Compound interest boost for accessed/cited nodes
            q_boost = (
                "UPDATE wiki_nodes SET "
                "  activation_score = math::min(10.0, activation_score + math::log(1 + access_count) * $boost), "
                "  compound_value = compound_value + math::log(1 + backlink_count) * $cite_bonus "
                "WHERE project_id = $pid AND (access_count > 0 OR backlink_count > 0)"
            )
            res = await db._safe_query(q_boost, {
                "pid": pid, "boost": _BOOST_FACTOR, "cite_bonus": _CITATION_BONUS,
            })
            boost_count = self._count_affected(res)
            if boost_count > 0:
                report.actions.append(DreamAction(
                    action_type="boost",
                    rationale=f"{boost_count} nodes received compound interest",
                    confidence=1.0,
                ))

        except Exception as e:
            report.errors.append(f"Physics error: {e}")
            logger.error(f"🌙 Phase LIGHT error: {e}")

        report.duration = time.time() - t0
        logger.info(f"🌙 Phase LIGHT: {report.action_count} actions in {report.duration:.2f}s")
        return report

    # ════════════════════════════════════════
    #  Phase 2: DEEP — Structural Analysis
    # ════════════════════════════════════════

    async def _phase_deep(self, pid: str) -> PhaseReport:
        report = PhaseReport(phase=DreamPhase.DEEP)
        t0 = time.time()
        db = self._get_db()
        if not db:
            report.errors.append("No database connection")
            return report

        try:
            # 2a. Orphan detection — nodes with zero in/out edges
            q_orphans = (
                "SELECT id, title, activation_score FROM wiki_nodes "
                "WHERE project_id = $pid "
                "  AND count(->depends_on) = 0 AND count(<-depends_on) = 0 "
                "  AND count(->extends) = 0 AND count(<-extends) = 0 "
                "ORDER BY activation_score ASC LIMIT 50"
            )
            res = await db._safe_query(q_orphans, {"pid": pid})
            orphans = db._extract_result(res) or []
            for o in orphans:
                report.actions.append(DreamAction(
                    action_type="orphan_detect",
                    target_nodes=[str(o.get("id", ""))],
                    rationale=f"Orphan: {o.get('title', '?')} (activation={o.get('activation_score', 0):.2f})",
                    confidence=1.0,
                ))

            # 2b. Fragility hotspots — high fan-in + low confidence
            q_fragile = (
                "SELECT id, title, confidence, count(<-depends_on) AS fan_in "
                "FROM wiki_nodes "
                "WHERE project_id = $pid AND confidence < 0.5 "
                "ORDER BY fan_in DESC LIMIT 10"
            )
            res = await db._safe_query(q_fragile, {"pid": pid})
            fragile = db._extract_result(res) or []
            for f in fragile:
                fan_in = f.get("fan_in", 0)
                if fan_in >= 2:
                    report.actions.append(DreamAction(
                        action_type="fragility_alert",
                        target_nodes=[str(f.get("id", ""))],
                        rationale=f"{f.get('title', '?')} (fan_in={fan_in}, conf={f.get('confidence', 0):.2f})",
                        confidence=f.get("confidence", 0),
                    ))

            # 2c. Hub detection — nodes with highest connectivity (knowledge pillars)
            q_hubs = (
                "SELECT id, title, "
                "  count(->depends_on) + count(<-depends_on) + count(->extends) + count(<-extends) AS degree "
                "FROM wiki_nodes WHERE project_id = $pid "
                "ORDER BY degree DESC LIMIT 5"
            )
            res = await db._safe_query(q_hubs, {"pid": pid})
            hubs = db._extract_result(res) or []
            for h in hubs:
                deg = h.get("degree", 0)
                if deg >= 3:
                    report.actions.append(DreamAction(
                        action_type="hub_identify",
                        target_nodes=[str(h.get("id", ""))],
                        rationale=f"Knowledge pillar: {h.get('title', '?')} (degree={deg})",
                        confidence=1.0,
                    ))

        except Exception as e:
            report.errors.append(f"Structural analysis error: {e}")
            logger.error(f"🌙 Phase DEEP error: {e}")

        report.duration = time.time() - t0
        logger.info(f"🌙 Phase DEEP: {report.action_count} findings in {report.duration:.2f}s")
        return report

    # ════════════════════════════════════════
    #  Phase 3: REM — LLM-Powered Synthesis
    # ════════════════════════════════════════

    async def _phase_rem(self, pid: str) -> PhaseReport:
        report = PhaseReport(phase=DreamPhase.REM)
        t0 = time.time()
        db = self._get_db()
        llm = self._get_llm()
        if not db or not llm:
            report.errors.append("No DB or LLM available")
            return report

        try:
            # Select multiple anchor nodes for multi-pair bridging
            q_anchors = (
                "SELECT id, title, body, embedding FROM wiki_nodes "
                "WHERE project_id = $pid AND memory_horizon = 'long_term' "
                "  AND activation_score > 0.3 "
                "ORDER BY rand() LIMIT $batch"
            )
            res = await db._safe_query(q_anchors, {"pid": pid, "batch": _SYNTHESIS_BATCH})
            anchors = db._extract_result(res) or []

            for anchor in anchors:
                anchor_id = anchor.get("id")
                vec = anchor.get("embedding")
                if not anchor_id or not vec:
                    continue

                # Find semantically similar but graph-disconnected node
                q_sim = (
                    "SELECT id, title, body, "
                    "  vector::similarity::cosine(embedding, $vec) AS sim "
                    "FROM wiki_nodes "
                    "WHERE project_id = $pid AND id != $aid "
                    "ORDER BY sim DESC LIMIT 3"
                )
                res2 = await db._safe_query(q_sim, {"pid": pid, "aid": anchor_id, "vec": vec})
                candidates = db._extract_result(res2) or []

                for target in candidates:
                    sim = target.get("sim", 0)
                    if sim < _SIM_THRESHOLD:
                        continue

                    target_id = target.get("id")
                    # Check if already connected
                    q_check = (
                        "SELECT count() AS cnt FROM depends_on "
                        "WHERE in = $a AND out = $b"
                    )
                    check_res = await db._safe_query(q_check, {"a": anchor_id, "b": target_id})
                    existing = db._extract_result(check_res)
                    if existing and existing[0].get("cnt", 0) > 0:
                        continue

                    # LLM synthesis
                    synthesis = await self._llm_bridge(
                        llm, anchor, target, sim
                    )
                    if not synthesis:
                        continue

                    # Persist synthesis node
                    new_id = f"syn-{uuid.uuid4().hex[:8]}"
                    node_data = {
                        "id": new_id,
                        "title": synthesis["title"],
                        "body": synthesis["summary"],
                        "type": "synthesis",
                        "status": "candidate",
                        "project_id": pid,
                        "layer": self._ctx.layer if self._ctx else 3,
                        "memory_horizon": "summary",
                        "confidence": 0.75,
                        "activation_score": 2.0,
                        "compound_value": 0.0,
                        "source_format": "md",
                    }
                    await db.upsert_knowledge_node(node_data)

                    # Create edges via LET-binding (V7.2)
                    for edge_target in [anchor_id, target_id]:
                        q_edge = (
                            "LET $__from = type::record('wiki_nodes', [$pid, $nid]); "
                            "LET $__to = type::record('wiki_nodes', $target); "
                            "RELATE $__from->extends->$__to SET source='dream_rem', confidence=0.75;"
                        )
                        await db._safe_query(q_edge, {
                            "pid": pid, "nid": new_id, "target": edge_target,
                        })

                    report.actions.append(DreamAction(
                        action_type="synthesize",
                        target_nodes=[str(anchor_id), str(target_id), new_id],
                        rationale=f"Bridged '{anchor.get('title','')}' ↔ '{target.get('title','')}' → '{synthesis['title']}' (sim={sim:.2f})",
                        confidence=sim,
                    ))
                    logger.info(f"🌌 REM: Synthesized '{synthesis['title']}' bridging sim={sim:.2f}")
                    break  # One synthesis per anchor

        except Exception as e:
            report.errors.append(f"REM synthesis error: {e}")
            logger.error(f"🌙 Phase REM error: {e}")

        report.duration = time.time() - t0
        logger.info(f"🌙 Phase REM: {report.action_count} syntheses in {report.duration:.2f}s")
        return report

    # ════════════════════════════════════════
    #  Phase 4: WAKE — Pruning & Archival
    # ════════════════════════════════════════

    async def _phase_wake(self, pid: str) -> PhaseReport:
        report = PhaseReport(phase=DreamPhase.WAKE)
        t0 = time.time()
        db = self._get_db()
        if not db:
            report.errors.append("No database connection")
            return report

        try:
            # 4a. Find archive candidates (low activation, not load-bearing)
            q_prune = (
                "SELECT id, title, activation_score, confidence, "
                "  count(<-depends_on) AS fan_in "
                "FROM wiki_nodes "
                "WHERE project_id = $pid "
                "  AND activation_score < $threshold "
                "  AND status != 'frozen' AND status != 'archived' "
                "ORDER BY activation_score ASC LIMIT $batch"
            )
            res = await db._safe_query(q_prune, {
                "pid": pid, "threshold": _PRUNE_THRESHOLD, "batch": _ARCHIVE_BATCH,
            })
            candidates = db._extract_result(res) or []

            for c in candidates:
                fan_in = c.get("fan_in", 0)
                node_id = c.get("id")
                if not node_id:
                    continue

                # Safety: skip load-bearing nodes (high fan_in)
                if fan_in > 3:
                    report.actions.append(DreamAction(
                        action_type="prune_skip",
                        target_nodes=[str(node_id)],
                        rationale=f"Skipped '{c.get('title','')}': load-bearing (fan_in={fan_in})",
                        confidence=1.0,
                    ))
                    continue

                # Archive: set status to 'archived'
                q_archive = (
                    "UPDATE wiki_nodes SET status = 'archived', "
                    "  memory_horizon = 'working' "
                    "WHERE project_id = $pid AND id = $nid"
                )
                await db._safe_query(q_archive, {"pid": pid, "nid": node_id})
                report.actions.append(DreamAction(
                    action_type="archive",
                    target_nodes=[str(node_id)],
                    rationale=f"Archived '{c.get('title','')}' (activation={c.get('activation_score', 0):.3f})",
                    confidence=1.0,
                ))

            # 4b. Expired TTL cleanup
            q_ttl = (
                "UPDATE wiki_nodes SET status = 'archived' "
                "WHERE project_id = $pid AND status != 'archived' "
                "  AND ttl_hours IS NOT NONE AND ttl_hours > 0 "
                "  AND time::unix(created_at) + (ttl_hours * 3600) < time::unix(time::now())"
            )
            await db._safe_query(q_ttl, {"pid": pid})

        except Exception as e:
            report.errors.append(f"Pruning error: {e}")
            logger.error(f"🌙 Phase WAKE error: {e}")

        report.duration = time.time() - t0
        logger.info(f"🌙 Phase WAKE: {report.action_count} prune actions in {report.duration:.2f}s")
        return report

    # ════════════════════════════════════════
    #  Health Metrics
    # ════════════════════════════════════════

    async def _compute_health(self, pid: str) -> KnowledgeHealthReport:
        h = KnowledgeHealthReport()
        db = self._get_db()
        if not db:
            return h

        try:
            # Total + active nodes
            q = "SELECT count() AS total FROM wiki_nodes WHERE project_id = $pid"
            res = await db._safe_query(q, {"pid": pid})
            rows = db._extract_result(res) or []
            h.total_nodes = rows[0].get("total", 0) if rows else 0

            q2 = "SELECT count() AS active FROM wiki_nodes WHERE project_id = $pid AND status != 'archived'"
            res2 = await db._safe_query(q2, {"pid": pid})
            rows2 = db._extract_result(res2) or []
            h.active_nodes = rows2[0].get("active", 0) if rows2 else 0

            # Averages
            q3 = (
                "SELECT math::mean(confidence) AS avg_conf, math::mean(activation_score) AS avg_act "
                "FROM wiki_nodes WHERE project_id = $pid AND status != 'archived'"
            )
            res3 = await db._safe_query(q3, {"pid": pid})
            rows3 = db._extract_result(res3) or []
            if rows3:
                h.avg_confidence = rows3[0].get("avg_conf", 0) or 0
                h.avg_activation = rows3[0].get("avg_act", 0) or 0

            # Trend heuristic
            if h.avg_activation > 3.0:
                h.trend = "growing"
            elif h.avg_activation < 0.5:
                h.trend = "decaying"
            elif h.orphan_count > h.total_nodes * 0.3:
                h.trend = "fragmenting"
            else:
                h.trend = "stable"

        except Exception as e:
            logger.warning(f"Health metrics error: {e}")

        return h

    # ════════════════════════════════════════
    #  LLM Bridge Helper
    # ════════════════════════════════════════

    async def _llm_bridge(self, llm: Any, anchor: dict, target: dict, sim: float) -> dict | None:
        prompt = (
            f"系统发现两个知识节点语义相似度 {sim:.2f} 但无图连接。\n"
            f"分析深层关联，生成一个桥接概念。\n"
            f'返回 JSON: {{"title": "概念名", "summary": "≤200字融合总结"}}\n\n'
            f"节点A ({anchor.get('title','')}):\n{str(anchor.get('body',''))[:1200]}\n\n"
            f"节点B ({target.get('title','')}):\n{str(target.get('body',''))[:1200]}"
        )
        try:
            import re, json
            resp = await llm.call([{"role": "user", "content": prompt}])
            m = re.search(r'\{.*\}', resp.text, re.DOTALL)
            if m:
                return json.loads(m.group(0))
        except Exception as e:
            logger.warning(f"LLM bridge failed: {e}")
        return None

    # ════════════════════════════════════════
    #  Utilities
    # ════════════════════════════════════════

    def _get_db(self) -> Any:
        # Primary: registry-injected 'db' service (set by main.py at startup)
        if self._ctx:
            db = self._ctx.registry.get_service("db")
            if db is not None:
                return db
            # Fallback: surreal_atlas plugin exposes its db handle
            atlas = self._ctx.registry.get_service("atlas")
            if atlas and hasattr(atlas, "_db"):
                return atlas._db
        return None

    def _get_llm(self) -> Any:
        return self._ctx.llm if self._ctx else None

    @staticmethod
    def _count_affected(res: Any) -> int:
        if isinstance(res, list):
            return len(res)
        if isinstance(res, dict):
            return res.get("count", 0)
        return 0
