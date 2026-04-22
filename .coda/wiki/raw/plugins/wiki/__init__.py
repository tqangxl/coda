"""
Coda Knowledge Engine V6.0 — Wiki Subpackage
自主知识引擎: 文件即真理, SQLite-vec 即编译产物。

模块总览 (14 模块):
  akp_types       — AKP 协议核心数据类型
  akp_parser      — Markdown YAML Frontmatter 解析 + WeakPatterns 拦截
  atlas           — SQLite-vec + FTS5 统一索引层 (4D-Fusion Recall)
  storage         — 增量编译清单 + 四层存储管理器
  compiler        — 两阶段编译流水线 (7 步自愈)
  shadow_mirror   — 影子镜像 (二进制→Markdown) + 涟漪更新
  pii_sentinel    — 隐私海关 PII 检测与脱敏
  session_hooks   — 会话生命周期 + Wiki 诊断自愈
  search          — 高级搜索 (Boolean Ask, Unique-Source Priority)
  skill_tracker   — 技能评分 + TRIZ 矛盾矩阵 + 晋升阶梯 + 协调
  taxonomy        — PARA 分类 + 蒸馏 + 分片 + 链接解析 + 成熟度
  enricher        — 冲突检测 + 空洞分析 + 跨域桥接 + MOC + 主动探索
  coordination    — 交接 + 心跳 + 屏障 + 内存隔离 + 重试 + 审计
  engine          — WikiEngine 统一入口 (编排全部子模块)
"""

from .akp_types import (
    # Enums
    NodeType, NodeStatus, EpistemicTag, AuthorityLevel,
    RelationType, CompactionOp, PIIShield, PrivacyMode,
    QualityGate, StorageLayer,
    # Core dataclasses
    KnowledgeNode, KnowledgeRelation, FactAnchor,
    ConflictReport, CompactionInstruction, ManifestEntry,
    SessionCheckpoint, HandoffSlice, AuditLogEntry,
    WeakPatternViolation,
)

from .plugins.akp_parser import (
    parse_markdown_file, parse_markdown_content,
    serialize_node_to_markdown, validate_node, validate_file,
)

from .plugins.atlas import AtlasIndex

from .plugins.storage import CompilationManifest, WikiStorage

from .plugins.compiler import MemoryCompiler

from .plugins.shadow_mirror import ShadowMirror, RippleEngine

from .plugins.pii_sentinel import PIISentinel, PIIDetection, SanitizationResult

from .plugins.session_hooks import SessionLifecycle, WikiDoctor, WikiDiagnosis

from .plugins.search import WikiSearchEngine, SearchQuery, SearchResult, BooleanAskResult

from .plugins.skill_tracker import (
    SkillTracker, SkillRating,
    PromotionLadder, CoverageGap,
    StepClaiming, StepClaim,
    GovernanceEngine, StageGate, TaskGrade, AdvisorAdvice,
    TRIZContradiction, predict_contradictions,
    detect_coverage_gaps,
)

from .plugins.taxonomy import (
    PARAClassifier, PARAClassification, PARACategory,
    KnowledgeDistiller, DistillationCandidate,
    ASTChunker, TextChunk,
    MultiPassLinkResolver,
    ContextTree, ContextRule,
    MaturityModel, MaturityScore,
)

from .plugins.enricher import (
    ConflictDetector, ConflictDetection,
    GapAnalyzer, CognitiveGap,
    CrossDomainDiscovery, CrossDomainBridge,
    MOCGenerator,
    ActiveExplorer,
    ReaderLens,
)

from .plugins.coordination import (
    HandoffManager, HandoffPacket,
    AgentRegistry, AgentHeartbeat,
    TaskBarrier,
    MemoryIsolation,
    DeferralMonitor, DeferredTask, DeferralEscalation,
    RetryQueue, RetryEntry,
    AuditTrail,
    EngineContract, WIKI_CONTRACTS,
)

from .engine import WikiEngine, WikiEngineConfig, CompileResult


__version__ = "6.1.0"

__all__ = [
    # ── Core Types ──
    "NodeType", "NodeStatus", "EpistemicTag", "AuthorityLevel",
    "RelationType", "CompactionOp", "PIIShield", "PrivacyMode",
    "QualityGate", "StorageLayer",
    "KnowledgeNode", "KnowledgeRelation", "FactAnchor",
    "ConflictReport", "CompactionInstruction", "ManifestEntry",
    "SessionCheckpoint", "HandoffSlice", "AuditLogEntry",
    "WeakPatternViolation",
    # ── Parser ──
    "parse_markdown_file", "parse_markdown_content",
    "serialize_node_to_markdown", "validate_node", "validate_file",
    # ── Index ──
    "AtlasIndex",
    # ── Storage ──
    "CompilationManifest", "WikiStorage",
    # ── Compiler ──
    "MemoryCompiler",
    # ── Shadow & Ripple ──
    "ShadowMirror", "RippleEngine",
    # ── PII ──
    "PIISentinel", "PIIDetection", "SanitizationResult",
    # ── Session & Doctor ──
    "SessionLifecycle", "WikiDoctor", "WikiDiagnosis",
    # ── Search ──
    "WikiSearchEngine", "SearchQuery", "SearchResult", "BooleanAskResult",
    # ── Skills & Governance ──
    "SkillTracker", "SkillRating",
    "PromotionLadder", "CoverageGap",
    "StepClaiming", "StepClaim",
    "GovernanceEngine", "StageGate", "TaskGrade", "AdvisorAdvice",
    "TRIZContradiction", "predict_contradictions",
    "detect_coverage_gaps",
    # ── Taxonomy ──
    "PARAClassifier", "PARAClassification", "PARACategory",
    "KnowledgeDistiller", "DistillationCandidate",
    "ASTChunker", "TextChunk",
    "MultiPassLinkResolver",
    "ContextTree", "ContextRule",
    "MaturityModel", "MaturityScore",
    # ── Enricher ──
    "ConflictDetector", "ConflictDetection",
    "GapAnalyzer", "CognitiveGap",
    "CrossDomainDiscovery", "CrossDomainBridge",
    "MOCGenerator",
    "ActiveExplorer",
    "ReaderLens",
    # ── Coordination ──
    "HandoffManager", "HandoffPacket",
    "AgentRegistry", "AgentHeartbeat",
    "TaskBarrier",
    "MemoryIsolation",
    "DeferralMonitor", "DeferredTask", "DeferralEscalation",
    "RetryQueue", "RetryEntry",
    "AuditTrail",
    "EngineContract", "WIKI_CONTRACTS",
    # ── Engine (Unified Entry Point) ──
    "WikiEngine", "WikiEngineConfig", "CompileResult",
]
