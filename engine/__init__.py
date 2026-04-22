"""
Coda V5.2 Engine — 800% UNIFIED + Knowledge Engine V6.1
全自主、自进化、分布式 Agent 框架 — 32+ 支柱, 50+ 核心类

模块总览:
  Core:     state, agent_engine, cli, __main__
  LLM:      llm_caller, tool_schemas
  Tools:    tool_executor
  Safety:   git_checkpoint, hooks, commands (Sandbox/XML/MCP)
  Intel:    history, context, skill_factory, speculation, knowledge
  Social:   buddy (+ Personality), memory, styles
  Heal:     doctor
  Network:  swarm, transport (Server/Client/Bridge), mcp_connector
  Auth:     jwt_auth
  Cluster:  coordinator
  Evolve:   migration
  Storage:  db (SurrealDB 桥接层)
  Vector:   embedder (Qwen3-Embedding 本地向量化)
  Wiki:     wiki/ (Knowledge Engine V6.1 — 14 模块, 95+ 导出)
    ├── akp_types      — AKP 协议核心数据类型
    ├── akp_parser     — Markdown 解析 + WeakPatterns 拦截
    ├── atlas          — SQLite-vec + FTS5 (4D-Fusion)
    ├── storage        — 四层存储 + 编译清单
    ├── compiler       — 7 步自愈编译流水线
    ├── shadow_mirror  — 二进制影子镜像 + 涟漪更新
    ├── pii_sentinel   — PII 检测与脱敏
    ├── session_hooks  — 会话生命周期 + Wiki Doctor
    ├── search         — Boolean Ask + LLM 上下文组装
    ├── skill_tracker  — Elo 评分 + TRIZ + 阶段门控
    ├── taxonomy       — PARA + 蒸馏 + 分片 + 链接解析 + 成熟度
    ├── enricher       — 冲突检测 + 空洞分析 + 跨域桥接 + MOC
    ├── coordination   — 交接 + 心跳 + 屏障 + 重试 + 审计
    └── engine         — WikiEngine 统一入口 (编排全部子模块)
"""

from .base_types import (
    AgentStatus, LoopPhase, TaskStatus, TokenUsage, ToolCall, 
    IntentResult, TaskNode, PhaseTransition, SubTask, 
    SwarmPeer, SwarmMessage, SwarmRole, TaskDAG, DomainConfig
)
from .state import AppState, AppStateStore
from .agent_engine import AgentEngine
from .llm_caller import LLMResponse, GeminiCaller, ClaudeCaller, OpenAICaller, create_caller
from .tool_executor import ToolExecutor
from .tool_schemas import get_gemini_tools, get_generic_tool_schemas, get_openai_tool_schemas
from .git_checkpoint import GitCheckpoint
from .hooks import HookEngine, HookResult
from .history import HistoryCompactor
from .context import ContextDiscoverer
from .commands import SlashCommandRouter, MCPRegistry, XMLProtocol, SecuritySandbox
from .skill_factory import SkillFactory, SkillDefinition
from .buddy import BuddySystem, BuddyAlert, BuddyPersonality
from .memory import SessionMemory, TeamMemory, MemoryEntry
from .doctor import Doctor, DiagnosisResult
from .speculation import PromptSpeculation, SpeculationHint
from .swarm import SwarmNetwork
from .transport import SwarmServer, SwarmClient, LocalBridge
from .mcp_connector import MCPConnection, MCPManager
from .knowledge import KnowledgeGraph, VectorMemory, KnowledgeEntity
from .jwt_auth import JWT, JWTError
from .coordinator import CoordinatorEngine
from .styles import StyleManager, OutputStyle
from .migration import ModelMigrator, BetaFlags, ModelProfile
from .db import SurrealStore
from .identity import registry
from .embedder import QwenEmbedder, get_embedder, EMBEDDING_DIM
from .intent_engine import IntentEngine
from .advisor import (
    ModelCard, ModelTier, ModelSpecialty, ModelRegistry,
    AdvisorStrategy, AdvisorOpinion, AdvisorVerdict,
    AdvisorExecutorRouter,
)

# ── Wiki Knowledge Engine V6.1 ──
from .plugins.wiki import (
    # Engine (Unified Entry Point)
    WikiEngine, WikiEngineConfig, CompileResult,
    # Index & Search
    AtlasIndex, WikiSearchEngine, SearchQuery, SearchResult, BooleanAskResult,
    # Types
    KnowledgeNode, KnowledgeRelation, FactAnchor, NodeType, NodeStatus,
    EpistemicTag, AuthorityLevel, RelationType,
    # Storage & Compilation
    WikiStorage, CompilationManifest, MemoryCompiler,
    # Intelligence
    ShadowMirror, RippleEngine, PIISentinel,
    # Session & Governance
    SessionLifecycle, WikiDoctor,
    SkillTracker, GovernanceEngine, StepClaiming,
    PromotionLadder,
    # Taxonomy
    PARAClassifier, PARACategory,
    KnowledgeDistiller,
    ASTChunker,
    MultiPassLinkResolver,
    ContextTree,
    MaturityModel, MaturityScore,
    # Enricher
    ConflictDetector,
    GapAnalyzer,
    CrossDomainDiscovery,
    MOCGenerator,
    ActiveExplorer,
    # Coordination
    HandoffManager, HandoffPacket,
    AgentRegistry, AgentHeartbeat,
    TaskBarrier,
    MemoryIsolation,
    RetryQueue,
    AuditTrail,
    DeferralMonitor,
    WIKI_CONTRACTS,
)

__version__ = "5.2.0"

__all__ = [
    # Core
    "AgentEngine",
    "AppState", "AppStateStore", "AgentStatus", "LoopPhase", "TokenUsage", "ToolCall",
    "IntentResult", "TaskNode", "PhaseTransition",
    # LLM
    "LLMResponse", "GeminiCaller", "ClaudeCaller", "OpenAICaller", "create_caller",
    # Tools
    "ToolExecutor",
    "get_gemini_tools", "get_generic_tool_schemas", "get_openai_tool_schemas",
    # Safety
    "GitCheckpoint", "HookEngine", "HookResult", "SecuritySandbox",
    # Intelligence
    "HistoryCompactor", "ContextDiscoverer",
    "SkillFactory", "SkillDefinition",
    "PromptSpeculation", "SpeculationHint",
    "KnowledgeGraph", "VectorMemory", "KnowledgeEntity",
    # Commands
    "SlashCommandRouter", "MCPRegistry", "XMLProtocol",
    # MCP
    "MCPConnection", "MCPManager",
    # Experience
    "BuddySystem", "BuddyAlert", "BuddyPersonality",
    "SessionMemory", "TeamMemory", "MemoryEntry",
    "StyleManager", "OutputStyle",
    # Resilience
    "Doctor", "DiagnosisResult",
    # Auth
    "JWT", "JWTError",
    # Connectivity
    "SwarmNetwork", "SwarmPeer", "SwarmMessage", "SwarmRole",
    "SwarmServer", "SwarmClient", "LocalBridge",
    "CoordinatorEngine", "SubTask", "TaskStatus",
    # Evolution
    "ModelMigrator", "BetaFlags", "ModelProfile",
    # Storage
    "SurrealStore",
    "registry",
    # Vector
    "QwenEmbedder", "get_embedder", "EMBEDDING_DIM",
    # Intent
    "IntentEngine", "TaskDAG", "DomainConfig",
    # ═══ Universal Advisor Engine ═══
    "ModelCard", "ModelTier", "ModelSpecialty", "ModelRegistry",
    "AdvisorStrategy", "AdvisorOpinion", "AdvisorVerdict",
    "AdvisorExecutorRouter",
    # ═══ Wiki Knowledge Engine V6.1 ═══
    # Engine
    "WikiEngine", "WikiEngineConfig", "CompileResult",

    # Wiki Index & Search
    "AtlasIndex", "WikiSearchEngine", "SearchQuery", "SearchResult", "BooleanAskResult",

    # Wiki Types
    "KnowledgeNode", "KnowledgeRelation", "FactAnchor", "NodeType", "NodeStatus",
    "EpistemicTag", "AuthorityLevel", "RelationType",

    # Wiki Storage
    "WikiStorage", "CompilationManifest", "MemoryCompiler",

    # Wiki Intelligence & Governance
    "ShadowMirror", "RippleEngine", "PIISentinel",
    "SessionLifecycle", "WikiDoctor",
    "SkillTracker", "GovernanceEngine", "StepClaiming",
    "PromotionLadder",

    # Wiki Taxonomy
    "PARAClassifier", "PARACategory",
    "KnowledgeDistiller",
    "ASTChunker",
    "MultiPassLinkResolver",
    "ContextTree",
    "MaturityModel", "MaturityScore",

    # Wiki Enricher
    "ConflictDetector",
    "GapAnalyzer",
    "CrossDomainDiscovery",
    "MOCGenerator", "ActiveExplorer",

    # Coordination
    "HandoffManager", "HandoffPacket",
    "AgentRegistry", "AgentHeartbeat",
    "TaskBarrier", "MemoryIsolation",
    "WIKI_CONTRACTS",
]
