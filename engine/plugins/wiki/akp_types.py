"""
Coda Knowledge Engine V6.0 — AKP Core Types
Coda Knowledge Protocol (AKP) 的核心数据类型定义。

设计原则:
  - 每个知识节点 (KnowledgeNode) 是一个带 YAML frontmatter 的 Markdown 文件的内存表示
  - 三层权威防线 (Authority Hierarchy) 防止幻觉污染
  - 结构化实体建模 (Owletto) 支持强类型关系
  - 事实级锚点 (Fact-Level Anchoring) 实现行级版本追踪
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any


# ════════════════════════════════════════════
#  枚举类型 (Enums)
# ════════════════════════════════════════════

class NodeType(str, Enum):
    """知识节点类型。"""
    ENTITY = "entity"
    CONCEPT = "concept"
    TECHNIQUE = "technique"
    DECISION = "decision"
    SYNTHESIS = "synthesis"
    PATTERN = "pattern"
    SOURCE = "source"
    CODE = "code"        # 代码文件 (Python, Rust, Go, ...)
    DATA = "data"        # 数据/标记语言文件 (JSON, YAML, HTML, CSS, Markdown)


class NodeStatus(str, Enum):
    """知识节点生命周期状态。"""
    DRAFT = "draft"
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    FROZEN = "frozen"
    ARCHIVED = "archived"
    ORPHAN = "orphan"


class EpistemicTag(str, Enum):
    """认知确信度标记 (三级强制分档)。"""
    FACT = "fact"            # 事实 (客观真理/已验证)
    CONFIRMED = "confirmed"
    INFERRED = "inferred"
    SPECULATIVE = "speculative"


class AuthorityLevel(str, Enum):
    """权威来源层级 (三层防线)。"""
    EXPLICIT = "explicit"    # 人类/测试验证, 权重天花板 10.0
    SYSTEM = "system"        # Agent 逻辑推导, 权重天花板 6.0
    INFERRED = "inferred"    # 模型猜测, 权重天花板 4.0

    @property
    def weight_ceiling(self) -> float:
        ceilings = {
            AuthorityLevel.EXPLICIT: 10.0,
            AuthorityLevel.SYSTEM: 6.0,
            AuthorityLevel.INFERRED: 4.0,
        }
        return ceilings[self]


class RelationType(str, Enum):
    """关系语义类型 (Owletto 结构化建模)。"""
    DEPENDS_ON = "depends_on"
    EXTENDS = "extends"
    CONTRADICTS = "contradicts"
    SUPERSEDES = "supersedes"
    GROUNDS = "grounds"        # 支撑
    IMPLIES = "implies"        # 隐含
    TENSIONS_WITH = "tensions_with"  # 冲突但不矛盾
    REFERENCES = "references"
    PART_OF = "part_of"
    RELATED_TO = "related_to"

    @property
    def inverse(self) -> RelationType:
        inverses: dict[RelationType, RelationType] = {
            RelationType.DEPENDS_ON: RelationType.GROUNDS,
            RelationType.GROUNDS: RelationType.DEPENDS_ON,
            RelationType.EXTENDS: RelationType.PART_OF,
            RelationType.PART_OF: RelationType.EXTENDS,
            RelationType.CONTRADICTS: RelationType.CONTRADICTS,
            RelationType.SUPERSEDES: RelationType.REFERENCES,
            RelationType.IMPLIES: RelationType.GROUNDS,
            RelationType.TENSIONS_WITH: RelationType.TENSIONS_WITH,
            RelationType.REFERENCES: RelationType.REFERENCES,
            RelationType.RELATED_TO: RelationType.RELATED_TO,
        }
        return inverses.get(self, RelationType.RELATED_TO)


class CompactionOp(str, Enum):
    """事实蒸馏 DSL 操作指令 (Palinode)。"""
    KEEP = "KEEP"
    UPDATE = "UPDATE"
    MERGE = "MERGE"
    SUPERSEDE = "SUPERSEDE"
    ARCHIVE = "ARCHIVE"


class PIIShield(str, Enum):
    """PII 脱敏状态。"""
    RAW = "raw"
    SANITIZED = "sanitized"
    ENCRYPTED = "encrypted"


class PrivacyMode(str, Enum):
    """隐私保护等级。"""
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    PERMISSIVE = "permissive"


class QualityGate(str, Enum):
    """深度标准门禁状态。"""
    PASSED = "passed"
    BELOW_MINIMUM = "below_minimum"
    PENDING_REVIEW = "pending_review"


class StorageLayer(str, Enum):
    """四层存储层级 (文件夹映射, 历史兼容)。"""
    RAW = "raw"              # L0: 原始素材 (只读)
    CANDIDATES = "candidates" # L1: 待验证
    CORE = "core"            # L2: 核心知识
    CONTROL = "control"      # L3: 系统控制


class KnowledgeLayer(int, Enum):
    """
    联邦知识栈层级 (Federation Hierarchy)。

    L0 — 公共基座 (法律法规/行业标准): 全局只读，所有项目可见。
    L1 — 组织层  (集团/机构制度):      组织内只读，下属单位可挂载。
    L2 — 部门层  (团队/项目公共库):    部门读写，跨部门可订阅。
    L3 — 个人层  (个人笔记/活跃项目):  仅本人读写，可向上提升。
    """
    PUBLIC = 0    # L0
    ORG = 1       # L1
    DEPT = 2      # L2
    PERSONAL = 3  # L3

    @property
    def is_readonly_by_default(self) -> bool:
        """L0 和 L1 层默认为只读。"""
        return self.value <= 1

    @property
    def label(self) -> str:
        labels = {0: "公共基座", 1: "组织层", 2: "部门层", 3: "个人层"}
        return labels[self.value]


class MemoryHorizon(str, Enum):
    """
    知识节点的时间维度分类 (Memory Horizon)。

    决定节点的生命周期管理、LLM 调用优先级和配额压力下的降级行为。

    LONG_TERM  — 长期记忆: 稳定核心知识，高置信度，跨会话持久。
                  示例: 架构决策、已验证的业务规则、领域模型。
    SHORT_TERM — 短期记忆: 临时工作知识，会话级有效，定期回收。
                  示例: 当前任务上下文、调试快照、临时 TODO。
    SUMMARY    — 概述/总结: 由多个源节点提炼而来的 MOC 或摘要。
                  示例: 每日编译报告、API 文档摘要、审计结论。
    WORKING    — 工作记忆: 极短暂的过程状态，仅在单次操作期间有效。
                  示例: 推理链中间步骤、流式解析缓冲区。
    """
    LONG_TERM  = "long_term"
    SHORT_TERM = "short_term"
    SUMMARY    = "summary"
    WORKING    = "working"

    @property
    def ttl_hours_default(self) -> float | None:
        """默认生存时间 (小时)。None = 永久保留。"""
        return {
            MemoryHorizon.LONG_TERM:  None,
            MemoryHorizon.SHORT_TERM: 24.0,
            MemoryHorizon.SUMMARY:    168.0,  # 7 天
            MemoryHorizon.WORKING:    1.0,
        }[self]

    @property
    def llm_priority(self) -> int:
        """
        LLM 调用优先级 (越高越不容易被跳过)。
        在配额压力下，低优先级的 horizon 率先降级或跳过。
        """
        return {
            MemoryHorizon.LONG_TERM:  4,  # 最高保护
            MemoryHorizon.SUMMARY:    3,
            MemoryHorizon.SHORT_TERM: 2,
            MemoryHorizon.WORKING:    1,  # 最先跳过
        }[self]

    @property
    def scenario_label(self) -> str:
        """映射到 resolve_model_hint 的 scenario 参数。"""
        return {
            MemoryHorizon.LONG_TERM:  "advisor",    # 用最好的模型处理
            MemoryHorizon.SUMMARY:    "compiler",
            MemoryHorizon.SHORT_TERM: "enrichment",
            MemoryHorizon.WORKING:    "search",
        }[self]

    @property
    def max_body_chars(self) -> int:
        """允许送入 LLM 的最大正文字符数 (防止超长输入消耗配额)。"""
        return {
            MemoryHorizon.LONG_TERM:  8000,
            MemoryHorizon.SUMMARY:    4000,
            MemoryHorizon.SHORT_TERM: 2000,
            MemoryHorizon.WORKING:    500,
        }[self]

    @property
    def compile_depth(self) -> str:
        """
        编译深度策略:
            full    — 全量解析 + 嵌入 + 关系抽取
            shallow — 基础解析 + 嵌入，跳过关系抽取
            index   — 仅更新索引，不重新嵌入
            skip    — 完全跳过 LLM 处理
        """
        return {
            MemoryHorizon.LONG_TERM:  "full",
            MemoryHorizon.SUMMARY:    "shallow",
            MemoryHorizon.SHORT_TERM: "shallow",
            MemoryHorizon.WORKING:    "index",
        }[self]

# ════════════════════════════════════════════
#  核心数据类 (Core Dataclasses)
# ════════════════════════════════════════════

@dataclass
class FactAnchor:
    """
    事实级锚点 (Palinode: <!-- fact:slug -->)。
    实现结构化实体 (函数/类/方法) 或 Markdown 内部行级的跨版本追踪。
    """
    slug: str
    content: str
    line_number: int = 0
    version: int = 1
    last_modified: float = field(default_factory=time.time)
    
    # ── V6.5 增强: 独立引索支持 ──
    entity_type: str | None = None  # e.g., "function", "class"
    node_id: str | None = None      # 对应的独立节点 ID (如果已提取)
    references: list[str] = field(default_factory=list) # 此实体引用的其它 slug/ID
    meta: dict[str, Any] = field(default_factory=dict)  # 解析器特定元数据

    @property
    def html_comment(self) -> str:
        return f"<!-- fact:{self.slug} -->"


@dataclass
class KnowledgeNode:
    """
    AKP 知识节点 — Markdown 文件或代码文件的内存表示。
    
    每个节点对应 Wiki/knowledge/ 下的一个 .md 文件。
    YAML frontmatter 中的所有字段在此映射为强类型属性。
    """
    # ── 必要标识 ──
    id: str = field(default_factory=lambda: f"akp-{uuid.uuid4().hex[:8]}")
    title: str = ""
    
    # ── 分类与生命周期 ──
    node_type: NodeType = NodeType.CONCEPT
    status: NodeStatus = NodeStatus.DRAFT
    
    # ── 认知诚信 ──
    confidence: float = 0.5
    epistemic_tag: EpistemicTag = EpistemicTag.SPECULATIVE
    authority: AuthorityLevel = AuthorityLevel.INFERRED
    load_bearing: bool = False
    falsifiable: bool = False
    falsification: str = ""
    
    # ── 隐私与安全 ──
    pii_shield: PIIShield = PIIShield.RAW
    
    # ── 内容 ──
    body: str = ""
    facts: list[FactAnchor] = field(default_factory=list)
    links: list[str] = field(default_factory=list)      # 知识连接 (ID 列表)
    
    # ── 溯源 ──
    source_origin_hash: str = ""
    verified_by: str = ""  # task-uuid
    references: list[str] = field(default_factory=list)
    
    # ── 因果依赖 ──
    depends_on: list[str] = field(default_factory=list)
    extends: str = ""
    contradicts: list[str] = field(default_factory=list)
    superseded_by: str = ""
    
    # ── 质量指标 ──
    insight_density: int = 5  # 1-10
    quality_gate: QualityGate = QualityGate.PENDING_REVIEW
    word_count: int = 0
    backlink_count: int = 0
    access_count: int = 0
    activation_score: float = 1.0  # 激活分值, 随时间衰减
    
    # ── 元数据 ──
    file_path: str = ""
    content_hash: str = ""
    last_audit: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    frozen_reason: str = ""
    truncated: bool = False
    original_length: int = 0
    
    # ── 代码解析元数据 ──
    language: str = ""               # 源语言标识 (python, rust, json, ...)
    
    # ── 联邦图谱元数据 (V7.0) ──
    project_id: str = "default"          # 所属项目/库 ID
    layer: int = 3                       # KnowledgeLayer 值 (0=L0公共, 1=L1组织, 2=L2部门, 3=L3个人)
    readonly: bool = False               # 是否只读 (L0/L1 默认 True)
    source_format: str = "md"            # 源文件格式: md/pdf/docx/xlsx/pptx/html/py...
    compound_value: float = 0.0          # 知识复利价值 (DreamCycle 计算)

    # ── 时间维度 (Memory Horizon, V7.1) ──
    memory_horizon: MemoryHorizon = MemoryHorizon.LONG_TERM
    # 自定义 TTL (小时)，None = 使用 horizon 默认值，0 = 立即回收
    ttl_hours: float | None = None

    # ── 编译追踪 ──
    derived_from_sources: list[str] = field(default_factory=list)
    embedding_hash: str = ""

    def compute_content_hash(self) -> str:
        """计算内容的 SHA-256 哈希, 用于实质性变更检测。"""
        raw = f"{self.title}\n{self.body}".encode("utf-8")
        self.content_hash = hashlib.sha256(raw).hexdigest()
        return self.content_hash

    def compute_word_count(self) -> int:
        """计算正文字数 (中英文混合)。"""
        import re
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', self.body))
        english_words = len(re.findall(r'[a-zA-Z]+', self.body))
        self.word_count = chinese_chars + english_words
        return self.word_count

    def apply_activation_decay(self, decay_rate: float = 0.95, interval_hours: float = 24.0) -> None:
        """应用激活衰减 (模拟短期→长期记忆转化)。"""
        hours_elapsed = (time.time() - self.updated_at) / 3600
        decay_steps = hours_elapsed / interval_hours
        self.activation_score *= decay_rate ** decay_steps

    def touch(self) -> None:
        """访问节点: 增加访问计数和激活分值。"""
        self.access_count += 1
        self.activation_score = min(10.0, self.activation_score + 0.5)
        self.updated_at = time.time()

    def check_depth_standard(self) -> QualityGate:
        """检查是否达到深度标准及格线。"""
        self.compute_word_count()
        
        if self.node_type == NodeType.SOURCE:
            # Source Summary: 500-1500 字
            if self.word_count < 500:
                self.quality_gate = QualityGate.BELOW_MINIMUM
                return self.quality_gate
        elif self.node_type == NodeType.ENTITY:
            # Entity Page: 至少 3 个外链 + 2 个来源引用
            outlinks = len(self.depends_on) + len(self.references)
            if outlinks < 3 or len(self.references) < 2:
                self.quality_gate = QualityGate.BELOW_MINIMUM
                return self.quality_gate
        elif self.node_type == NodeType.SYNTHESIS:
            # Synthesis: 至少引用 3 个不同来源
            if len(self.references) < 3:
                self.quality_gate = QualityGate.BELOW_MINIMUM
                return self.quality_gate
        
        self.quality_gate = QualityGate.PASSED
        return self.quality_gate

    def to_frontmatter_dict(self) -> dict[str, Any]:
        """导出为 YAML frontmatter 兼容的字典。"""
        return {
            "id": self.id,
            "title": self.title,
            "type": self.node_type.value,
            "status": self.status.value,
            "confidence": self.confidence,
            "epistemic_tag": self.epistemic_tag.value,
            "load_bearing": self.load_bearing,
            "pii_shield": self.pii_shield.value,
            "falsifiable": self.falsifiable,
            "falsification": self.falsification,
            "depends_on": self.depends_on,
            "extends": self.extends,
            "contradicts": self.contradicts,
            "source_origin_hash": self.source_origin_hash,
            "verified_by": self.verified_by,
            "insight_density": self.insight_density,
            "references": self.references,
            "last_audit": self.last_audit,
            "memory_horizon": self.memory_horizon.value,
            "ttl_hours": self.ttl_hours,
        }

    def to_dict(self) -> dict[str, Any]:
        """完整序列化 (用于持久化)。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KnowledgeNode:
        """从字典恢复节点。"""
        node = cls()
        for k, v in data.items():
            if k == "node_type" and isinstance(v, str):
                node.node_type = NodeType(v)
            elif k == "status" and isinstance(v, str):
                node.status = NodeStatus(v)
            elif k == "epistemic_tag" and isinstance(v, str):
                node.epistemic_tag = EpistemicTag(v)
            elif k == "authority" and isinstance(v, str):
                node.authority = AuthorityLevel(v)
            elif k == "pii_shield" and isinstance(v, str):
                node.pii_shield = PIIShield(v)
            elif k == "quality_gate" and isinstance(v, str):
                node.quality_gate = QualityGate(v)
            elif k == "memory_horizon" and isinstance(v, str):
                node.memory_horizon = MemoryHorizon(v)
            elif hasattr(node, k):
                setattr(node, k, v)
        return node


@dataclass
class KnowledgeRelation:
    """
    知识节点间的关系边。
    支持双向一致性 (inverse_type) 和承重标记。
    """
    from_id: str
    to_id: str
    relation_type: RelationType = RelationType.RELATED_TO
    weight: float = 1.0
    load_bearing: bool = False
    confidence: float = 1.0
    source: str = ""  # API | LLM | Human | Test
    created_at: float = field(default_factory=time.time)

    @property
    def inverse_type(self) -> RelationType:
        return self.relation_type.inverse

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_id": self.from_id,
            "to_id": self.to_id,
            "relation_type": self.relation_type.value,
            "weight": self.weight,
            "load_bearing": self.load_bearing,
            "confidence": self.confidence,
            "source": self.source,
            "created_at": self.created_at,
        }


@dataclass
class ConflictReport:
    """
    苏格拉底调解冲突报告。
    当两个知识节点发生逻辑冲突时生成。
    """
    conflict_id: str = field(default_factory=lambda: f"conflict-{uuid.uuid4().hex[:8]}")
    conflict_type: str = "logical"  # logical | temporal | authority
    node_a_id: str = ""
    node_b_id: str = ""
    node_a_claim: str = ""
    node_b_claim: str = ""
    evidence_a: list[str] = field(default_factory=list)
    evidence_b: list[str] = field(default_factory=list)
    verdict: str = ""  # a_wins | b_wins | both_valid | unresolved
    winning_id: str = ""
    confidence: float = 0.0
    arbitrator: str = ""  # agent_id
    created_at: float = field(default_factory=time.time)
    resolved_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CompactionInstruction:
    """
    蒸馏 DSL 指令 (Palinode 模式)。
    LLM 输出此指令, 由确定性执行器处理。
    """
    operation: CompactionOp
    target_fact_slug: str
    new_content: str = ""
    merge_with_slug: str = ""
    reason: str = ""


@dataclass
class ManifestEntry:
    """
    增量编译清单条目。
    追踪 raw/ 源文件的哈希及其派生的 Wiki 页面。
    """
    source_path: str
    content_hash: str   # SHA-256
    file_size: int = 0
    mime_type: str = ""
    last_compiled: float = 0.0
    derived_pages: list[str] = field(default_factory=list)  # Wiki 页面 ID 列表
    status: str = "pending"  # pending | compiled | stale | error
    error_message: str = ""
    retry_count: int = 0

    def is_stale(self, current_hash: str) -> bool:
        """检查源文件是否已变更。"""
        return self.content_hash != current_hash

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass 
class SessionCheckpoint:
    """
    会话断点 (用于断点续传和状态恢复)。
    """
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    phase: str = ""
    completed_tasks: list[str] = field(default_factory=list)
    current_task: str = ""
    files_modified: list[str] = field(default_factory=list)
    pending_writes: list[dict[str, Any]] = field(default_factory=list)
    progress_pct: float = 0.0
    next_steps: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HandoffSlice:
    """
    交接协议上下文切片 (Tracecraft)。
    上一个 Agent/Task 完成时生成, 下一个接手时消费。
    """
    task_id: str
    completed_items: list[str] = field(default_factory=list)
    current_state: str = ""
    key_findings: list[str] = field(default_factory=list)
    next_suggestions: list[str] = field(default_factory=list)
    created_by: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuditLogEntry:
    """
    审计日志条目 (基于动词的日志)。
    """
    action: str  # ingest | query | lint | synthesize | merge | archive | conflict_resolve
    target: str = ""
    detail: str = ""
    conversation_id: str = ""
    task_id: str = ""
    agent_id: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_markdown_block(self) -> str:
        """生成 Markdown 日志块。"""
        from datetime import datetime, timezone
        iso_time = datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat()
        lines = [f"## [{iso_time}] {self.action}"]
        if self.target:
            lines.append(f"- **Target**: {self.target}")
        if self.detail:
            lines.append(f"- **Detail**: {self.detail}")
        if self.agent_id:
            lines.append(f"- **Agent**: {self.agent_id}")
        if self.task_id:
            lines.append(f"- **Task**: {self.task_id}")
        lines.append("")
        return "\n".join(lines)


@dataclass
class WeakPatternViolation:
    """
    语义弱信号拦截结果。
    """
    node_id: str
    violation_type: str  # short_description | vague_verb | missing_source | low_confidence
    detail: str = ""
    severity: str = "warning"  # warning | error

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.violation_type}: {self.detail} (node: {self.node_id})"
