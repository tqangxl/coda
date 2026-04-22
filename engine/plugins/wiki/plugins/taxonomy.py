"""
Coda Knowledge Engine V6.0 — Taxonomy Manager
动态分类法 + PARA 生命周期 + 多轮链接解析 + 成熟度模型。

Blueprint Coverage:
  §2.2  P.A.R.A 生命周期分类 (Meowary)
  §3.4  结构化实体建模 (Owletto)
  §4.7  熵驱动知识蒸馏 (Distillation)
  §4.8  AST 感知分片 (Tree-sitter Chunking)
  §4.9  Context Tree 路径语义注入
  §5.5  多轮链接解析 (Multi-Pass Resolver)
  §13.6 成熟度模型 (Maturity Model)
  §15.5 反向链接强制闭环
"""

from __future__ import annotations

from ..base_plugin import WikiPlugin, WikiHook, WikiPluginContext

import hashlib
import json
import logging
import math
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ..akp_types import (
    KnowledgeNode, KnowledgeRelation, NodeType, NodeStatus,
    RelationType, EpistemicTag, AuthorityLevel, QualityGate,
)
from .atlas import AtlasIndex

logger = logging.getLogger("Coda.wiki.taxonomy")


# ════════════════════════════════════════════
#  §2.2 P.A.R.A 生命周期分类
# ════════════════════════════════════════════

class PARACategory(str, Enum):
    """P.A.R.A 生命周期分类 (Meowary)。"""
    PROJECTS = "projects"    # 有明确终点
    AREAS = "areas"          # 长期/无终点
    RESOURCES = "resources"  # 通用参考
    ARCHIVES = "archives"    # 归档


@dataclass
class PARAClassification:
    """PARA 分类结果。"""
    node_id: str
    category: PARACategory
    confidence: float = 0.5
    reason: str = ""
    archive_candidates: list[str] = field(default_factory=list)


class PARAClassifier(WikiPlugin):
    """
    P.A.R.A 生命周期分类器。
    """
    name = "para"

    # ... keywords remains same
    AREA_KEYWORDS = {
        "architecture", "security", "principle", "policy", "standard",
        "protocol", "framework", "core", "foundation",
        "架构", "安全", "原则", "策略", "标准", "协议", "框架",
    }
    RESOURCE_KEYWORDS = {
        "comparison", "benchmark", "reference", "guide", "best-practice",
        "template", "pattern", "tutorial", "overview",
        "对比", "基准", "参考", "指南", "最佳实践", "模板", "模式",
    }

    async def initialize(self, ctx: WikiPluginContext) -> None:
        logger.info("📂 PARA Classifier plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        return None

    def classify(self, node: KnowledgeNode) -> PARAClassification:
        """基于节点属性自动分类。"""
        title_lower = node.title.lower()
        body_lower = node.body[:500].lower()
        text = f"{title_lower} {body_lower}"

        # 已归档
        if node.status == NodeStatus.ARCHIVED:
            return PARAClassification(
                node_id=node.id,
                category=PARACategory.ARCHIVES,
                confidence=0.95,
                reason="Status is archived",
            )

        # 长期领域
        area_hits = sum(1 for kw in self.AREA_KEYWORDS if kw in text)
        if area_hits >= 2 or node.load_bearing:
            return PARAClassification(
                node_id=node.id,
                category=PARACategory.AREAS,
                confidence=min(0.5 + area_hits * 0.15, 0.95),
                reason=f"Area keywords: {area_hits}, load_bearing: {node.load_bearing}",
            )

        # 通用参考
        resource_hits = sum(1 for kw in self.RESOURCE_KEYWORDS if kw in text)
        if resource_hits >= 2:
            return PARAClassification(
                node_id=node.id,
                category=PARACategory.RESOURCES,
                confidence=min(0.5 + resource_hits * 0.15, 0.9),
                reason=f"Resource keywords: {resource_hits}",
            )

        # 项目 (有明确目标，通常有时间维度)
        project_signals = (
            "sprint" in text or "milestone" in text or "deadline" in text
            or "feature" in text or "release" in text
            or "task" in text or "phase" in text
            or node.node_type == NodeType.DECISION
        )
        if project_signals:
            return PARAClassification(
                node_id=node.id,
                category=PARACategory.PROJECTS,
                confidence=0.6,
                reason="Project signals detected",
            )

        # 默认归为资源
        return PARAClassification(
            node_id=node.id,
            category=PARACategory.RESOURCES,
            confidence=0.4,
            reason="Default classification",
        )

    def detect_archive_candidates(
        self, atlas: AtlasIndex, stale_days: int = 90
    ) -> list[PARAClassification]:
        """检测可归档的候选知识 (长期未更新且非承重)。"""
        assert atlas._conn is not None
        threshold = time.time() - stale_days * 86400

        rows = atlas._conn.execute("""
            SELECT id, title, updated_at, load_bearing, status
            FROM nodes
            WHERE updated_at < ? AND load_bearing = 0 AND status != 'archived'
            ORDER BY updated_at ASC
            LIMIT 50
        """, (threshold,)).fetchall()

        candidates = []
        for row in rows:
            days_old = (time.time() - row["updated_at"]) / 86400
            candidates.append(PARAClassification(
                node_id=row["id"],
                category=PARACategory.ARCHIVES,
                confidence=min(0.5 + days_old / 365, 0.95),
                reason=f"Stale for {int(days_old)} days, non-load-bearing",
            ))
        return candidates


# ════════════════════════════════════════════
#  §4.7 熵驱动知识蒸馏
# ════════════════════════════════════════════

@dataclass
class DistillationCandidate:
    """蒸馏候选项。"""
    node_a_id: str
    node_b_id: str
    similarity: float
    action: str  # "discard" | "merge" | "keep_both"
    retain_id: str = ""
    reason: str = ""


class KnowledgeDistiller(WikiPlugin):
    """
    熵驱动知识蒸馏器。
    """
    name = "distiller"

    async def initialize(self, ctx: WikiPluginContext) -> None:
        logger.info("🧪 Distiller plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        return None

    @staticmethod
    def _simhash(text: str, bits: int = 64) -> int:
        """SimHash 指纹计算。"""
        weights = [0] * bits
        words = re.findall(r'\w+', text.lower())
        for word in words:
            h = int(hashlib.md5(word.encode()).hexdigest(), 16)
            for i in range(bits):
                if h & (1 << i):
                    weights[i] += 1
                else:
                    weights[i] -= 1
        return sum(1 << i for i in range(bits) if weights[i] > 0)

    @staticmethod
    def _hamming_distance(a: int, b: int, bits: int = 64) -> int:
        """汉明距离。"""
        xor = a ^ b
        return bin(xor).count('1')

    @staticmethod
    def _jaccard_similarity(text_a: str, text_b: str) -> float:
        """Jaccard 相似度。"""
        words_a = set(re.findall(r'\w+', text_a.lower()))
        words_b = set(re.findall(r'\w+', text_b.lower()))
        if not words_a and not words_b:
            return 1.0
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / len(union) if union else 0.0

    @staticmethod
    def _information_entropy(text: str) -> float:
        """信息熵计算 (字符级)。"""
        if not text:
            return 0.0
        counter = Counter(text)
        total = len(text)
        entropy = 0.0
        for count in counter.values():
            p = count / total
            if p > 0:
                entropy -= p * math.log2(p)
        return entropy

    def find_candidates(
        self, nodes: list[KnowledgeNode], threshold: float = 0.85
    ) -> list[DistillationCandidate]:
        """发现蒸馏候选对。"""
        candidates: list[DistillationCandidate] = []

        # 预计算 SimHash
        hashes = {node.id: self._simhash(node.body) for node in nodes}

        for i, node_a in enumerate(nodes):
            for node_b in nodes[i + 1:]:
                # 快速预筛选 (SimHash 汉明距离)
                dist = self._hamming_distance(hashes[node_a.id], hashes[node_b.id])
                if dist > 20:  # 距离太大，跳过
                    continue

                # 精确相似度 (Jaccard)
                sim = self._jaccard_similarity(node_a.body, node_b.body)
                if sim < threshold:
                    continue

                # 决定保留哪个 (信息熵更高)
                entropy_a = self._information_entropy(node_a.body)
                entropy_b = self._information_entropy(node_b.body)
                retain = node_a.id if entropy_a >= entropy_b else node_b.id
                discard = node_b.id if retain == node_a.id else node_a.id

                if sim >= 0.95:
                    action = "discard"
                elif sim >= threshold:
                    action = "merge"
                else:
                    action = "keep_both"

                candidates.append(DistillationCandidate(
                    node_a_id=node_a.id,
                    node_b_id=node_b.id,
                    similarity=sim,
                    action=action,
                    retain_id=retain,
                    reason=f"Entropy: {node_a.id}={entropy_a:.2f}, {node_b.id}={entropy_b:.2f}",
                ))

        return candidates


# ════════════════════════════════════════════
#  §4.8 AST 感知分片
# ════════════════════════════════════════════

@dataclass
class TextChunk:
    """文本分片。"""
    content: str
    chunk_type: str  # "heading" | "paragraph" | "code" | "list" | "ast_function" | "ast_class"
    start_line: int = 0
    end_line: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class ASTChunker(WikiPlugin):
    """
    AST 感知分片器。
    """
    name = "chunker"

    def __init__(self, ideal_chunk_size: int = 800, max_chunk_size: int = 1500):
        self._ideal_size = ideal_chunk_size
        self._max_size = max_chunk_size

    async def initialize(self, ctx: WikiPluginContext) -> None:
        logger.info("🧩 Chunker plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        return None

    def chunk_markdown(self, text: str) -> list[TextChunk]:
        """Markdown 感知分片 (Regex 模式)。"""
        chunks: list[TextChunk] = []
        lines = text.split('\n')
        current_chunk: list[str] = []
        current_type = "paragraph"
        chunk_start = 0
        in_code_block = False

        for i, line in enumerate(lines):
            # 代码块保护
            if line.strip().startswith('```'):
                in_code_block = not in_code_block
                if not in_code_block and current_chunk:
                    current_type = "code"

            # 标题断点 (最高优先)
            if not in_code_block and re.match(r'^#{1,3}\s', line):
                if current_chunk:
                    chunks.append(TextChunk(
                        content='\n'.join(current_chunk),
                        chunk_type=current_type,
                        start_line=chunk_start,
                        end_line=i - 1,
                    ))
                current_chunk = [line]
                current_type = "heading"
                chunk_start = i
                continue

            current_chunk.append(line)

            # 大小控制
            chunk_text = '\n'.join(current_chunk)
            if len(chunk_text) > self._max_size and not in_code_block:
                # 在最近的空行处断开
                split_at = len(current_chunk) - 1
                for j in range(len(current_chunk) - 1, max(0, len(current_chunk) - 10), -1):
                    if not current_chunk[j].strip():
                        split_at = j
                        break

                chunks.append(TextChunk(
                    content='\n'.join(current_chunk[:split_at + 1]),
                    chunk_type=current_type,
                    start_line=chunk_start,
                    end_line=chunk_start + split_at,
                ))
                current_chunk = current_chunk[split_at + 1:]
                chunk_start = i - len(current_chunk) + 1
                current_type = "paragraph"

        # 最后一块
        if current_chunk:
            chunks.append(TextChunk(
                content='\n'.join(current_chunk),
                chunk_type=current_type,
                start_line=chunk_start,
                end_line=len(lines) - 1,
            ))

        return [c for c in chunks if c.content.strip()]

    def chunk_code(self, code: str, language: str = "python") -> list[TextChunk]:
        """
        代码 AST 分片 (Tree-sitter 模式, graceful fallback)。
        如果 tree-sitter 不可用，退化为正则匹配函数/类定义。
        """
        try:
            return self._chunk_code_treesitter(code, language)
        except Exception:
            return self._chunk_code_regex(code, language)

    def _chunk_code_treesitter(self, code: str, language: str) -> list[TextChunk]:
        """Tree-sitter AST 分片。"""
        import tree_sitter_languages  # pyright: ignore[reportMissingImports]
        parser = tree_sitter_languages.get_parser(language)
        tree = parser.parse(code.encode())

        chunks: list[TextChunk] = []
        for node in tree.root_node.children:
            if node.type in ("function_definition", "class_definition",
                             "decorated_definition", "async_function_definition"):
                content = code[node.start_byte:node.end_byte]
                chunk_type = "ast_class" if "class" in node.type else "ast_function"
                chunks.append(TextChunk(
                    content=content,
                    chunk_type=chunk_type,
                    start_line=node.start_point[0],
                    end_line=node.end_point[0],
                    metadata={"node_type": node.type, "language": language},
                ))

        # 如果没有发现结构化节点，整体作为一个 chunk
        if not chunks:
            chunks.append(TextChunk(content=code, chunk_type="code"))

        return chunks

    def _chunk_code_regex(self, code: str, language: str) -> list[TextChunk]:
        """正则 fallback 分片 (函数/类定义检测)。"""
        chunks: list[TextChunk] = []
        lines = code.split('\n')

        # Python 函数/类定义模式
        patterns = {
            "python": r'^(class |def |async def )',
            "javascript": r'^(function |class |const \w+ = |export )',
            "typescript": r'^(function |class |const \w+ = |export |interface )',
            "rust": r'^(fn |pub fn |impl |struct |enum |trait )',
            "go": r'^(func |type )',
        }
        pattern = patterns.get(language, r'^(class |def |function )')
        current_chunk: list[str] = []
        chunk_start = 0

        for i, line in enumerate(lines):
            if re.match(pattern, line) and current_chunk:
                chunks.append(TextChunk(
                    content='\n'.join(current_chunk),
                    chunk_type="ast_function",
                    start_line=chunk_start,
                    end_line=i - 1,
                    metadata={"language": language},
                ))
                current_chunk = [line]
                chunk_start = i
            else:
                current_chunk.append(line)

        if current_chunk:
            chunks.append(TextChunk(
                content='\n'.join(current_chunk),
                chunk_type="ast_function",
                start_line=chunk_start,
                end_line=len(lines) - 1,
                metadata={"language": language},
            ))

        return [c for c in chunks if c.content.strip()]


# ════════════════════════════════════════════
#  §5.5 多轮链接解析器
# ════════════════════════════════════════════

@dataclass
class LinkIssue:
    """链接问题。"""
    source_id: str
    target_id: str
    issue_type: str  # "broken" | "one_way" | "speculative"
    resolved: bool = False


class MultiPassLinkResolver(WikiPlugin):
    """
    多轮链接解析器。
    """
    name = "link_resolver"

    def __init__(self, atlas: AtlasIndex | None = None):
        self._atlas = atlas

    async def initialize(self, ctx: WikiPluginContext) -> None:
        """插件初始化入口。"""
        if not self._atlas:
            self._atlas = ctx.atlas
        logger.info("🔗 Link Resolver plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        if hook == WikiHook.POST_COMPILE:
            return self.resolve()
        return None

    def resolve(self, max_passes: int = 3) -> dict[str, Any]:
        """多轮链接解析。"""
        report: dict[str, Any] = {
            "passes": 0,
            "broken_links": [],
            "one_way_links": [],
            "speculative_links": [],
            "fixed": 0,
        }
        if not self._atlas or not self._atlas._conn:
            return report

        for pass_num in range(max_passes):
            report["passes"] = pass_num + 1
            issues = self._scan_links()
            if not issues:
                break

            for issue in issues:
                if issue.issue_type == "broken":
                    report["broken_links"].append({
                        "source": issue.source_id,
                        "target": issue.target_id,
                    })
                elif issue.issue_type == "one_way":
                    report["one_way_links"].append({
                        "source": issue.source_id,
                        "target": issue.target_id,
                    })
                    # 自动补全反向链接
                    self._create_backlink(issue.target_id, issue.source_id)
                    report["fixed"] += 1
                elif issue.issue_type == "speculative":
                    report["speculative_links"].append({
                        "source": issue.source_id,
                        "target": issue.target_id,
                    })

        return report

    def _scan_links(self) -> list[LinkIssue]:
        """扫描所有链接问题。"""
        if not self._atlas or not self._atlas._conn:
            return []
        issues: list[LinkIssue] = []

        # 检测断链 (引用不存在的节点，但有 wanted pages)
        rows = self._atlas._conn.execute("""
            SELECT r.from_id, r.to_id, r.relation_type
            FROM relations r
            LEFT JOIN nodes n ON r.to_id = n.id
            WHERE n.id IS NULL
        """).fetchall()
        for row in rows:
            issues.append(LinkIssue(
                source_id=row["from_id"],
                target_id=row["to_id"],
                issue_type="speculative",
            ))

        # 检测单向链接 (A→B 存在但 B→A 不存在)
        rows = self._atlas._conn.execute("""
            SELECT r1.from_id, r1.to_id
            FROM relations r1
            WHERE r1.relation_type = 'references'
            AND NOT EXISTS (
                SELECT 1 FROM relations r2
                WHERE r2.from_id = r1.to_id
                AND r2.to_id = r1.from_id
            )
        """).fetchall()
        for row in rows:
            # 只对双向存在的节点生成 backlink
            if not self._atlas:
                continue
            target_exists = self._atlas.get_node(row["to_id"]) is not None
            if target_exists:
                issues.append(LinkIssue(
                    source_id=row["from_id"],
                    target_id=row["to_id"],
                    issue_type="one_way",
                ))

        return issues

    def _create_backlink(self, from_id: str, to_id: str) -> None:
        """创建反向链接。"""
        rel = KnowledgeRelation(
            from_id=from_id,
            to_id=to_id,
            relation_type=RelationType.REFERENCES,
            source="backlink_resolver",
        )
        if self._atlas:
            self._atlas.upsert_relation(rel)


# ════════════════════════════════════════════
#  §4.9 Context Tree 路径语义注入
# ════════════════════════════════════════════

@dataclass
class ContextRule:
    """路径上下文规则。"""
    path_pattern: str
    description: str
    inject_as_metadata: bool = True


class ContextTree(WikiPlugin):
    """
    Context Tree 路径语义注入器。
    """
    name = "context_tree"

    def __init__(self, config_path: str | Path | None = None):
        self._rules: list[ContextRule] = []
        self._config_path = config_path

    async def initialize(self, ctx: WikiPluginContext) -> None:
        """插件初始化入口。"""
        config_path = self._config_path or (Path(ctx.wiki_dir) / "CONTEXT_ENGINE.md")
        if config_path:
            self._load_config(config_path)
        else:
            self._init_defaults()
        logger.info("🌳 Context Tree plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        return None

    def _init_defaults(self) -> None:
        """初始化默认上下文规则。"""
        self._rules = [
            ContextRule("raw/", "Original source materials — treat as immutable evidence"),
            ContextRule("knowledge/entities/", "Verified entity definitions with structured schemas"),
            ContextRule("knowledge/concepts/", "Core concept explanations and mental models"),
            ContextRule("knowledge/techniques/", "Proven engineering techniques with implementation guidance"),
            ContextRule("knowledge/synthesis/", "Cross-source synthesis and comparative analysis"),
            ContextRule("knowledge/kyp/", "Know Your People — social context with privacy boundaries"),
            ContextRule("_meta/candidates/", "Unverified candidate knowledge — requires validation"),
            ContextRule("_meta/low_signal/", "Low quality content demoted by validation pipeline"),
        ]

    def _load_config(self, config_path: str | Path) -> None:
        """从 CONTEXT_ENGINE.md 加载上下文规则。"""
        path = Path(config_path)
        if not path.exists():
            self._init_defaults()
            return

        try:
            content = path.read_text(encoding="utf-8")
            # 解析 Markdown 列表格式的上下文规则
            for match in re.finditer(
                r'-\s*`([^`]+)`\s*[:：]\s*(.+)', content
            ):
                self._rules.append(ContextRule(
                    path_pattern=match.group(1),
                    description=match.group(2).strip(),
                ))
        except Exception as e:
            logger.warning(f"Failed to load context engine config: {e}")
            self._init_defaults()

    def get_context(self, file_path: str) -> str:
        """获取文件路径对应的上下文描述。"""
        normalized = file_path.replace('\\', '/')
        contexts = []
        for rule in self._rules:
            if rule.path_pattern in normalized:
                contexts.append(rule.description)
        return "; ".join(contexts) if contexts else ""

    def add_rule(self, path_pattern: str, description: str) -> None:
        """动态添加上下文规则。"""
        self._rules.append(ContextRule(path_pattern, description))


# ════════════════════════════════════════════
#  §13.6 成熟度模型
# ════════════════════════════════════════════

@dataclass
class MaturityScore:
    """工作区成熟度评分。"""
    overall: float  # 0-100
    dimensions: dict[str, float] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    grade: str = "D"  # A/B/C/D/F

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "dimensions": self.dimensions,
            "recommendations": self.recommendations,
            "grade": self.grade,
        }


class MaturityModel(WikiPlugin):
    """
    工作区成熟度模型 (OpenArche)。
    """
    name = "maturity"

    async def initialize(self, ctx: WikiPluginContext) -> None:
        logger.info("📈 Maturity Model plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        return None

    def evaluate(self, atlas: AtlasIndex) -> MaturityScore:
        """评估知识库成熟度。"""
        if not atlas._conn:
            return MaturityScore(overall=0.0)
        stats = atlas.get_stats()

        # 1. 覆盖度 (节点数量)
        node_count = stats["node_count"]
        coverage = min(node_count / 100, 1.0) * 100  # 100 节点满分

        # 2. 连通性 (关系密度)
        rel_count = stats["relation_count"]
        connectivity = min(rel_count / max(node_count * 2, 1), 1.0) * 100

        # 3. 验证度 (已验证节点比例)
        validated = atlas._conn.execute(
            "SELECT COUNT(*) c FROM nodes WHERE status = 'validated'"
        ).fetchone()["c"]
        validation = (validated / max(node_count, 1)) * 100

        # 4. 新鲜度 (30天内更新的节点比例)
        recent_threshold = time.time() - 30 * 86400
        recent = atlas._conn.execute(
            "SELECT COUNT(*) c FROM nodes WHERE updated_at > ?",
            (recent_threshold,)
        ).fetchone()["c"]
        freshness = (recent / max(node_count, 1)) * 100

        # 5. 深度 (平均字数)
        avg_words = atlas._conn.execute(
            "SELECT AVG(word_count) a FROM nodes"
        ).fetchone()["a"] or 0
        depth = min(avg_words / 500, 1.0) * 100  # 500 字满分

        # 6. 孤儿率 (低=好)
        orphans = len(atlas.find_orphans())
        orphan_penalty = max(0, 100 - (orphans / max(node_count, 1)) * 100)

        # 加权计算
        overall = (
            coverage * 0.15
            + connectivity * 0.20
            + validation * 0.20
            + freshness * 0.15
            + depth * 0.15
            + orphan_penalty * 0.15
        )

        # 等级
        if overall >= 80:
            grade = "A"
        elif overall >= 60:
            grade = "B"
        elif overall >= 40:
            grade = "C"
        elif overall >= 20:
            grade = "D"
        else:
            grade = "F"

        # 建议
        recommendations = []
        if coverage < 50:
            recommendations.append(f"Add more knowledge nodes (current: {node_count})")
        if connectivity < 30:
            recommendations.append(f"Create more inter-node relations (current: {rel_count})")
        if validation < 30:
            recommendations.append(f"Validate more nodes (validated: {validated}/{node_count})")
        if freshness < 30:
            recommendations.append(f"Update stale content (recent: {recent}/{node_count})")
        if depth < 40:
            recommendations.append(f"Improve content depth (avg words: {int(avg_words)})")
        if orphan_penalty < 50:
            recommendations.append(f"Link orphan pages (orphans: {orphans})")

        return MaturityScore(
            overall=round(overall, 1),
            dimensions={
                "coverage": round(coverage, 1),
                "connectivity": round(connectivity, 1),
                "validation": round(validation, 1),
                "freshness": round(freshness, 1),
                "depth": round(depth, 1),
                "orphan_penalty": round(orphan_penalty, 1),
            },
            recommendations=recommendations,
            grade=grade,
        )
