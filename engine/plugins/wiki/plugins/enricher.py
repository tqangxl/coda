"""
Coda Knowledge Engine V6.0 — Enricher & Conflict Detector
LLM 驱动的自动增强 + 矛盾检测 + 认知空洞分析。

Blueprint Coverage:
  §1.4  读者上下文透镜 (Reader-Context Lens)
  §9.3  认知空洞分析 (Gap Analysis)
  §9.5  不确定性驱动的主动探索
  §9.6  跨领域连接发现 (Cross-Domain Bridging)
  §10.2 物理证据门控 (Boolean Ask)
  §10.5 苏格拉底式调解 (Socratic Arbitration)
  §10.6 截断诚实标记
  §15.1 内容地图 (MOCs - Maps of Content)
  §15.3 矛盾标志 (Dissonance Flagging)
"""

from __future__ import annotations

from ..base_plugin import WikiPlugin, WikiHook, WikiPluginContext

import hashlib
import json
import logging
import math
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..akp_types import (
    KnowledgeNode, KnowledgeRelation, NodeType, NodeStatus,
    RelationType, EpistemicTag, AuthorityLevel, ConflictReport,
    QualityGate,
)
from .atlas import AtlasIndex

logger = logging.getLogger("Coda.wiki.enricher")


# ════════════════════════════════════════════
#  §10.5 苏格拉底式调解 — 冲突检测器
# ════════════════════════════════════════════

@dataclass
class ConflictDetection:
    """冲突检测结果。"""
    node_a_id: str
    node_b_id: str
    node_a_title: str
    node_b_title: str
    conflict_type: str  # "contradiction" | "tension" | "inconsistency" | "outdated"
    severity: str  # "critical" | "moderate" | "minor"
    evidence_a: str
    evidence_b: str
    resolution_suggestion: str = ""
    detected_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_a_id": self.node_a_id,
            "node_b_id": self.node_b_id,
            "node_a_title": self.node_a_title,
            "node_b_title": self.node_b_title,
            "conflict_type": self.conflict_type,
            "severity": self.severity,
            "evidence_a": self.evidence_a,
            "evidence_b": self.evidence_b,
            "resolution_suggestion": self.resolution_suggestion,
            "detected_at": self.detected_at,
        }


class ConflictDetector(WikiPlugin):
    """
    苏格拉底式调解系统。
    """
    name = "conflict"

    def __init__(self, atlas: AtlasIndex | None = None):
        self._atlas = atlas

    async def initialize(self, ctx: WikiPluginContext) -> None:
        if not self._atlas:
            self._atlas = ctx.atlas
        logger.info("⚔️ Conflict Detector plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        return None

    def detect_all(self) -> list[ConflictDetection]:
        """运行全量冲突检测。"""
        conflicts: list[ConflictDetection] = []
        conflicts.extend(self._detect_explicit_contradictions())
        conflicts.extend(self._detect_temporal_inconsistencies())
        conflicts.extend(self._detect_load_bearing_risks())
        return conflicts

    def _detect_explicit_contradictions(self) -> list[ConflictDetection]:
        """检测显式矛盾关系。"""
        if not self._atlas or not self._atlas._conn:
            return []
        conflicts = []

        rows = self._atlas._conn.execute("""
            SELECT r.from_id, r.to_id,
                   n1.title AS from_title, n1.body_preview AS from_body,
                   n2.title AS to_title, n2.body_preview AS to_body,
                   n1.confidence AS from_conf, n2.confidence AS to_conf
            FROM relations r
            JOIN nodes n1 ON r.from_id = n1.id
            JOIN nodes n2 ON r.to_id = n2.id
            WHERE r.relation_type = 'contradicts'
        """).fetchall()

        for row in rows:
            # 确定严重性: 两个高置信节点矛盾 = 严重
            severity = "critical" if min(row["from_conf"], row["to_conf"]) > 0.7 else "moderate"

            conflicts.append(ConflictDetection(
                node_a_id=row["from_id"],
                node_b_id=row["to_id"],
                node_a_title=row["from_title"],
                node_b_title=row["to_title"],
                conflict_type="contradiction",
                severity=severity,
                evidence_a=row["from_body"][:200] if row["from_body"] else "",
                evidence_b=row["to_body"][:200] if row["to_body"] else "",
                resolution_suggestion=(
                    "Red-Blue Team arbitration recommended. "
                    "Consider running evidence comparison and keeping the one "
                    "with higher authority level."
                ),
            ))

        return conflicts

    def _detect_temporal_inconsistencies(self) -> list[ConflictDetection]:
        """检测时间序列不一致 (旧结论 vs 新证据)。"""
        if not self._atlas or not self._atlas._conn:
            return []
        conflicts = []

        # 查找同一实体类型的节点中，新旧结论不一致
        rows = self._atlas._conn.execute("""
            SELECT n1.id AS old_id, n1.title AS old_title,
                   n1.body_preview AS old_body, n1.updated_at AS old_time,
                   n2.id AS new_id, n2.title AS new_title,
                   n2.body_preview AS new_body, n2.updated_at AS new_time
            FROM nodes n1
            JOIN relations r ON r.from_id = n1.id
            JOIN nodes n2 ON r.to_id = n2.id
            WHERE r.relation_type = 'supersedes'
            AND n1.status NOT IN ('archived', 'frozen')
        """).fetchall()

        for row in rows:
            conflicts.append(ConflictDetection(
                node_a_id=row["old_id"],
                node_b_id=row["new_id"],
                node_a_title=row["old_title"],
                node_b_title=row["new_title"],
                conflict_type="outdated",
                severity="moderate",
                evidence_a=f"Older version (updated: {time.ctime(row['old_time'])})",
                evidence_b=f"Superseding version (updated: {time.ctime(row['new_time'])})",
                resolution_suggestion="Archive the older version and update all references.",
            ))

        return conflicts

    def _detect_load_bearing_risks(self) -> list[ConflictDetection]:
        """检测承重边风险 (低置信度承重节点)。"""
        if not self._atlas or not self._atlas._conn:
            return []
        conflicts = []

        # 承重节点但置信度低
        rows = self._atlas._conn.execute("""
            SELECT n.id, n.title, n.confidence, n.body_preview
            FROM nodes n
            WHERE n.load_bearing = 1 AND n.confidence < 0.5
        """).fetchall()

        for row in rows:
            # 计算下游依赖数量
            if not self._atlas or not self._atlas._conn:
                continue
            deps = self._atlas._conn.execute(
                "SELECT COUNT(*) c FROM relations WHERE from_id = ? AND load_bearing = 1",
                (row["id"],)
            ).fetchone()["c"]

            if deps > 0:
                conflicts.append(ConflictDetection(
                    node_a_id=row["id"],
                    node_b_id="",
                    node_a_title=row["title"],
                    node_b_title=f"({deps} downstream dependencies)",
                    conflict_type="inconsistency",
                    severity="critical",
                    evidence_a=f"Load-bearing node with low confidence ({row['confidence']:.2f})",
                    evidence_b=f"{deps} nodes depend on this through load-bearing edges",
                    resolution_suggestion=(
                        "URGENT: Verify or refute this load-bearing claim. "
                        "Cascade failure risk detected."
                    ),
                ))

        return conflicts

    def generate_conflict_report(
        self, node_a_id: str, node_b_id: str
    ) -> ConflictReport:
        """生成冲突报告 (用于苏格拉底式调解)。"""
        if not self._atlas:
            return ConflictReport(node_a_id=node_a_id, node_b_id=node_b_id)
        node_a = self._atlas.get_node(node_a_id) or {}
        node_b = self._atlas.get_node(node_b_id) or {}

        report = ConflictReport(
            node_a_id=node_a_id,
            node_b_id=node_b_id,
            conflict_type="contradiction",
            evidence_a=[str(node_a.get("body_preview", ""))],
            evidence_b=[str(node_b.get("body_preview", ""))],
        )

        # 证据加权: 运行结果 > 文档申明
        conf_a = float(node_a.get("confidence", 0))
        conf_b = float(node_b.get("confidence", 0))
        auth_a = node_a.get("authority", "inferred")
        auth_b = node_b.get("authority", "inferred")

        # 优先级: explicit > system > inferred
        auth_weight = {"explicit": 3, "system": 2, "inferred": 1}
        weight_a = conf_a * auth_weight.get(auth_a, 1)
        weight_b = conf_b * auth_weight.get(auth_b, 1)

        if weight_a > weight_b:
            report.verdict = f"Retain {node_a_id} (weight: {weight_a:.2f} vs {weight_b:.2f})"
            report.winning_id = node_a_id
        elif weight_b > weight_a:
            report.verdict = f"Retain {node_b_id} (weight: {weight_b:.2f} vs {weight_a:.2f})"
            report.winning_id = node_b_id
        else:
            report.verdict = "Inconclusive — manual review required"
            report.winning_id = ""

        report.confidence = abs(weight_a - weight_b) / max(weight_a + weight_b, 0.01)
        return report


# ════════════════════════════════════════════
#  §9.3 认知空洞分析
# ════════════════════════════════════════════

@dataclass
class CognitiveGap:
    """认知空洞。"""
    topic: str
    gap_type: str  # "weak_connection" | "missing_topic" | "shallow_coverage" | "stale"
    severity: float  # 0-1
    related_nodes: list[str] = field(default_factory=list)
    suggestion: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "gap_type": self.gap_type,
            "severity": self.severity,
            "related_nodes": self.related_nodes,
            "suggestion": self.suggestion,
        }


class GapAnalyzer(WikiPlugin):
    """
    认知空洞分析器。
    """
    name = "gap_analyzer"

    def __init__(self, atlas: AtlasIndex | None = None):
        self._atlas = atlas

    async def initialize(self, ctx: WikiPluginContext) -> None:
        if not self._atlas:
            self._atlas = ctx.atlas
        logger.info("🕳️ Gap Analyzer plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        return None

    def analyze(self) -> list[CognitiveGap]:
        """执行全面的认知空洞分析。"""
        gaps: list[CognitiveGap] = []
        gaps.extend(self._detect_weak_connections())
        gaps.extend(self._detect_shallow_coverage())
        gaps.extend(self._detect_stale_knowledge())
        gaps.extend(self._detect_wanted_topics())
        return gaps

    def _detect_weak_connections(self) -> list[CognitiveGap]:
        """检测弱连接区域 (节点存在但关系稀疏)。"""
        if not self._atlas or not self._atlas._conn:
            return []
        gaps = []

        # 有节点但关系数极少
        rows = self._atlas._conn.execute("""
            SELECT n.id, n.title, n.word_count,
                   (SELECT COUNT(*) FROM relations r
                    WHERE r.from_id = n.id OR r.to_id = n.id) AS rel_count
            FROM nodes n
            WHERE n.word_count > 100  -- 有实质内容
            ORDER BY rel_count ASC
            LIMIT 20
        """).fetchall()

        for row in rows:
            if row["rel_count"] < 2:
                gaps.append(CognitiveGap(
                    topic=row["title"],
                    gap_type="weak_connection",
                    severity=0.7 if row["rel_count"] == 0 else 0.4,
                    related_nodes=[row["id"]],
                    suggestion=f"Node '{row['title']}' has only {row['rel_count']} connections. "
                               "Consider linking to related concepts.",
                ))

        return gaps

    def _detect_shallow_coverage(self) -> list[CognitiveGap]:
        """检测浅层覆盖 (内容不足)。"""
        if not self._atlas or not self._atlas._conn:
            return []
        gaps = []

        rows = self._atlas._conn.execute("""
            SELECT id, title, word_count, insight_density
            FROM nodes
            WHERE word_count < 100 AND status != 'archived'
            ORDER BY word_count ASC
            LIMIT 20
        """).fetchall()

        for row in rows:
            gaps.append(CognitiveGap(
                topic=row["title"],
                gap_type="shallow_coverage",
                severity=0.6,
                related_nodes=[row["id"]],
                suggestion=f"Node '{row['title']}' has only {row['word_count']} words. "
                           "Needs substantive expansion.",
            ))

        return gaps

    def _detect_stale_knowledge(self) -> list[CognitiveGap]:
        """检测过时知识 (长期未更新)。"""
        if not self._atlas or not self._atlas._conn:
            return []
        gaps = []
        threshold = time.time() - 60 * 86400  # 60 天

        rows = self._atlas._conn.execute("""
            SELECT id, title, updated_at
            FROM nodes
            WHERE updated_at < ? AND status = 'validated'
            ORDER BY updated_at ASC
            LIMIT 15
        """, (threshold,)).fetchall()

        for row in rows:
            days_old = (time.time() - row["updated_at"]) / 86400
            gaps.append(CognitiveGap(
                topic=row["title"],
                gap_type="stale",
                severity=min(days_old / 180, 0.9),
                related_nodes=[row["id"]],
                suggestion=f"Node '{row['title']}' hasn't been updated in {int(days_old)} days. "
                           "May contain outdated information.",
            ))

        return gaps

    def _detect_wanted_topics(self) -> list[CognitiveGap]:
        """检测需求主题 (被引用但不存在)。"""
        if not self._atlas:
            return []
        wanted = self._atlas.find_wanted_pages()
        gaps = []

        for w in wanted[:15]:
            gaps.append(CognitiveGap(
                topic=w["wanted_id"],
                gap_type="missing_topic",
                severity=min(w["ref_count"] / 10, 0.95),
                suggestion=f"Topic '{w['wanted_id']}' is referenced {w['ref_count']} times but doesn't exist. "
                           "Consider creating this knowledge node.",
            ))

        return gaps


# ════════════════════════════════════════════
#  §9.6 跨领域连接发现
# ════════════════════════════════════════════

@dataclass
class CrossDomainBridge:
    """跨领域桥接。"""
    domain_a: str
    domain_b: str
    bridge_concept: str
    bridge_nodes: list[str] = field(default_factory=list)
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain_a": self.domain_a,
            "domain_b": self.domain_b,
            "bridge_concept": self.bridge_concept,
            "bridge_nodes": self.bridge_nodes,
            "confidence": self.confidence,
        }


class CrossDomainDiscovery(WikiPlugin):
    """
    跨领域连接发现器。
    """
    name = "discovery"

    def __init__(self, atlas: AtlasIndex | None = None):
        self._atlas = atlas

    async def initialize(self, ctx: WikiPluginContext) -> None:
        if not self._atlas:
            self._atlas = ctx.atlas
        logger.info("🌉 Bridge Discovery plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        return None

    def find_bridges(self) -> list[CrossDomainBridge]:
        """发现跨领域桥接。"""
        if not self._atlas or not self._atlas._conn:
            return []
        bridges: list[CrossDomainBridge] = []

        # 获取所有节点类型分布
        type_nodes: dict[str, list[dict[str, Any]]] = defaultdict(list)
        rows = self._atlas._conn.execute(
            "SELECT id, title, node_type, body_preview FROM nodes"
        ).fetchall()

        for row in rows:
            type_nodes[row["node_type"]].append(dict(row))

        # 寻找跨类型共享的关键词
        type_keywords: dict[str, set[str]] = {}
        for node_type, nodes in type_nodes.items():
            keywords: set[str] = set()
            for node in nodes:
                words = set(re.findall(r'\b\w{4,}\b', (node.get("body_preview") or "").lower()))
                keywords.update(words)
            type_keywords[node_type] = keywords

        # 发现跨类型共享但非通用的词汇
        types = list(type_keywords.keys())
        for i, type_a in enumerate(types):
            for type_b in types[i + 1:]:
                shared = type_keywords[type_a] & type_keywords[type_b]
                # 移除通用词
                shared -= {
                    "that", "this", "with", "from", "have", "will", "been",
                    "more", "some", "does", "when", "what", "each", "very",
                    "about", "which", "their", "other", "than", "them",
                }
                if len(shared) > 5:
                    # 找到有意义的共享概念
                    key_bridges = sorted(shared, key=len, reverse=True)[:3]
                    bridges.append(CrossDomainBridge(
                        domain_a=type_a,
                        domain_b=type_b,
                        bridge_concept=", ".join(key_bridges),
                        confidence=min(len(shared) / 50, 0.8),
                    ))

        return bridges


# ════════════════════════════════════════════
#  §15.1 叙事型 MOC 生成器
# ════════════════════════════════════════════

class MOCGenerator(WikiPlugin):
    """
    内容地图生成器 (Maps of Content)。
    """
    name = "moc_generator"

    def __init__(self, atlas: AtlasIndex | None = None):
        self._atlas = atlas

    async def initialize(self, ctx: WikiPluginContext) -> None:
        if not self._atlas:
            self._atlas = ctx.atlas
        logger.info("🗺️ MOC Generator plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        return None

    def generate_moc(self, category: str | None = None) -> str:
        """生成叙事型 MOC。"""
        if not self._atlas or not self._atlas._conn:
            return "# Knowledge Map\n\nAtlas or database connection not available.\n"

        query = "SELECT id, title, node_type, status, confidence, word_count FROM nodes"
        params: tuple[Any, ...] = ()
        if category:
            query += " WHERE node_type = ?"
            params = (category,)
        query += " ORDER BY confidence DESC, word_count DESC"

        rows = self._atlas._conn.execute(query, params).fetchall()
        if not rows:
            return "# Knowledge Map\n\nNo knowledge nodes found.\n"

        # 按类型分组
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            groups[row["node_type"]].append(dict(row))

        lines = ["# 📚 Knowledge Map (Auto-Generated)\n"]
        lines.append(f"> Total: {len(rows)} nodes across {len(groups)} categories\n")

        for node_type, nodes in sorted(groups.items()):
            lines.append(f"\n## {node_type.title()} ({len(nodes)} nodes)\n")
            lines.append(self._generate_narrative(node_type, nodes))

            for node in nodes[:20]:
                status_icon = {"validated": "✅", "draft": "📝", "candidate": "🔶"}.get(
                    node["status"], "❓"
                )
                lines.append(
                    f"- {status_icon} **[[{node['id']}|{node['title']}]]** "
                    f"(conf: {node['confidence']:.2f}, {node['word_count']} words)"
                )

        # 添加关系概览
        if not self._atlas:
            return "\n".join(lines) + "\n"
        stats = self._atlas.get_stats()
        lines.append(f"\n---\n")
        lines.append(f"\n## 🔗 Graph Overview\n")
        lines.append(f"- Nodes: {stats['node_count']}")
        lines.append(f"- Relations: {stats['relation_count']}")
        lines.append(f"- Types: {json.dumps(stats['type_distribution'])}")

        return "\n".join(lines) + "\n"

    def _generate_narrative(self, node_type: str, nodes: list[dict[str, Any]]) -> str:
        """生成类型叙事。"""
        narratives = {
            "concept": (
                "These are the core **mental models** and abstractions that form the "
                "foundation of understanding. Start here to build a framework for "
                "interpreting more specific techniques and entities.\n"
            ),
            "technique": (
                "Proven **engineering methods** ready for application. Each technique "
                "includes implementation guidance and has been validated through practice.\n"
            ),
            "entity": (
                "Concrete **things** with defined properties — tools, systems, people, "
                "or organizations that appear across multiple contexts.\n"
            ),
            "synthesis": (
                "**Cross-source analysis** that connects insights from multiple origins. "
                "These represent the highest-value knowledge distilled from synthesis.\n"
            ),
            "decision": (
                "Important **architectural choices** with documented rationale. "
                "Review these to understand why the system is built this way.\n"
            ),
            "pattern": (
                "Recurring **patterns** observed across multiple sessions. "
                "These have been validated through repetition.\n"
            ),
        }
        return narratives.get(node_type, f"Knowledge nodes of type '{node_type}'.\n")


# ════════════════════════════════════════════
#  §1.4 读者上下文透镜 + §9.5 主动探索
# ════════════════════════════════════════════

@dataclass
class ReaderLens:
    """读者上下文透镜。"""
    focus_topics: list[str] = field(default_factory=list)
    tech_context: str = ""
    expertise_level: str = "intermediate"  # beginner | intermediate | expert
    decision_style: str = "pragmatic"  # pragmatic | theoretical | experimental


class ActiveExplorer(WikiPlugin):
    """
    不确定性驱动的主动探索引擎。
    """
    name = "explorer"

    def __init__(self, atlas: AtlasIndex | None = None):
        self._atlas = atlas

    async def initialize(self, ctx: WikiPluginContext) -> None:
        if not self._atlas:
            self._atlas = ctx.atlas
        logger.info("🔭 Active Explorer plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        return None

    def find_uncertain_hypotheses(self, top_k: int = 10) -> list[dict[str, Any]]:
        """发现不确定假设。"""
        if not self._atlas or not self._atlas._conn:
            return []

        rows = self._atlas._conn.execute("""
            SELECT id, title, confidence, epistemic_tag, body_preview
            FROM nodes
            WHERE epistemic_tag IN ('speculative', 'inferred')
            AND confidence < 0.5
            AND status != 'archived'
            ORDER BY confidence ASC
            LIMIT ?
        """, (top_k,)).fetchall()

        return [
            {
                "id": row["id"],
                "title": row["title"],
                "confidence": row["confidence"],
                "epistemic_tag": row["epistemic_tag"],
                "preview": row["body_preview"][:150] if row["body_preview"] else "",
                "question": f"Regarding '{row['title']}': this hypothesis has low confidence "
                            f"({row['confidence']:.2f}). Should we investigate further?",
            }
            for row in rows
        ]

    def find_untested_claims(self, top_k: int = 10) -> list[dict[str, Any]]:
        """发现未经测试的声明。"""
        if not self._atlas or not self._atlas._conn:
            return []

        rows = self._atlas._conn.execute("""
            SELECT id, title, confidence, verified_by
            FROM nodes
            WHERE (verified_by IS NULL OR verified_by = '')
            AND confidence > 0.6
            AND status = 'validated'
            ORDER BY confidence DESC
            LIMIT ?
        """, (top_k,)).fetchall()

        return [
            {
                "id": row["id"],
                "title": row["title"],
                "confidence": row["confidence"],
                "question": f"'{row['title']}' is marked as validated (conf={row['confidence']:.2f}) "
                            "but has no verified_by task. Consider adding test verification.",
            }
            for row in rows
        ]

    def generate_exploration_agenda(self) -> dict[str, Any]:
        """生成探索议程。"""
        uncertain = self.find_uncertain_hypotheses(5)
        untested = self.find_untested_claims(5)

        return {
            "uncertain_hypotheses": uncertain,
            "untested_claims": untested,
            "total_items": len(uncertain) + len(untested),
            "priority_question": uncertain[0]["question"] if uncertain else (
                untested[0]["question"] if untested else "No exploration needed"
            ),
        }
