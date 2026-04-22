"""
Coda Knowledge Engine V6.1 — WikiEngine (Pluginized Facade)
统一 API 入口 + 插件化架构 + 动态域扩展。

集成所有 14 个 Wiki 子模块作为内部插件加载。
"""

from __future__ import annotations

from .base_plugin import WikiPlugin, WikiHook, WikiPluginContext, WikiPluginRegistry
from .. import Plugin  # Engine-level Plugin protocol

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from .akp_types import KnowledgeNode, NodeType, NodeStatus, EpistemicTag
from .plugins.akp_parser import parse_markdown_file, parse_markdown_content, validate_node
from .plugins.atlas import AtlasIndex
from .plugins.compiler import MemoryCompiler
from .plugins.coordination import (
    HandoffManager, HandoffPacket,
    AgentRegistry, AgentHeartbeat,
    TaskBarrier,
    MemoryIsolation,
    DeferralMonitor,
    RetryQueue, RetryEntry,
    AuditTrail,
    WIKI_CONTRACTS,
)
from .plugins.enricher import (
    ConflictDetector, ConflictDetection,
    GapAnalyzer, CognitiveGap,
    CrossDomainDiscovery, CrossDomainBridge,
    MOCGenerator,
    ActiveExplorer,
    ReaderLens,
)
from .plugins.pii_sentinel import PIISentinel
from .plugins.polyglot_parser import PolyglotParser
from .plugins.search import WikiSearchEngine, SearchQuery, SearchResult, BooleanAskResult
from .plugins.storage import WikiStorage, CompilationManifest
from .plugins.session_hooks import SessionLifecycle, WikiDoctor
from .plugins.shadow_mirror import ShadowMirror, RippleEngine
from .plugins.skill_tracker import (
    SkillTracker,
    PromotionLadder,
    StepClaiming,
    GovernanceEngine,
)
from .plugins.taxonomy import (
    PARAClassifier, PARACategory,
    KnowledgeDistiller, DistillationCandidate,
    ASTChunker,
    MultiPassLinkResolver,
    ContextTree,
    MaturityModel, MaturityScore,
)
from .plugins.crystallizer import Crystallizer
from .plugins.dream_cycle import DreamCycleService
from ...base_types import UniversalCognitivePacket
from ...llm_caller import create_caller, get_secret

logger = logging.getLogger("Coda.wiki.engine")


@dataclass
class WikiEngineConfig:
    """
    Wiki 引擎配置。
    
    联邦模式 (V7.0):
        project_id — 当前项目的唯一标识。若未指定，自动从 wiki_dir 父目录名派生。
        layer      — 当前项目所属的知识层级 (KnowledgeLayer: 0=公共/1=组织/2=部门/3=个人)。
        mounts     — 订阅的上游知识库 project_id 列表 (这些库的数据在搜索时可见)。
        promotion_mode — L3→L2 知识提升模式: "auto" (自动) | "approval" (需人工审批)。
    """
    wiki_dir: str | Path
    embedding_dim: int = 2048
    enable_embedding: bool = True
    enable_pii: bool = True
    enable_shadows: bool = True
    enable_ripple: bool = True
    enable_polyglot: bool = True  # 启用 15 语言代码解析
    heartbeat_ttl: float = 300
    agent_id: str = "commander"
    context_engine_path: str | Path | None = None

    # ── 联邦图谱配置 (V7.0) ──
    project_id: str = ""                     # 空字符串时自动从 wiki_dir 派生
    layer: int = 3                           # 默认 L3 个人层
    mounts: list[str] = field(default_factory=list)   # 订阅的上游库列表
    promotion_mode: str = "approval"         # "auto" | "approval"
    auto_promotion_threshold: float = 50.0   # 复利值达到多少时自动提升 (auto 模式)
    cross_dept_subscription: bool = True     # 是否允许跨部门订阅
    # 额外扫描路径 (V7.1) — 代码层配置，与环境变量 WIKI_SCAN_PATHS 共同作用
    extra_scan_paths: list[str | Path] = field(default_factory=list)

    def __post_init__(self) -> None:
        """自动推导 project_id (若未显式指定)。"""
        if not self.project_id:
            # 从 wiki_dir 父目录名生成安全的 project_id
            # 例如: d:/company/project_alpha/.Coda/wiki → "project_alpha"
            import re
            parent_name = Path(self.wiki_dir).resolve().parent.parent.name
            self.project_id = re.sub(r'[^a-zA-Z0-9_-]', '_', parent_name).lower() or "default"


@dataclass
class CompileResult:
    """编译结果摘要。"""
    files_processed: int = 0
    nodes_indexed: int = 0
    nodes_deleted: int = 0
    relations_extracted: int = 0
    errors: int = 0
    compile_time: float = 0
    pii_detections: int = 0
    conflicts: list[ConflictDetection] = field(default_factory=list)
    distillation_candidates: list[DistillationCandidate] = field(default_factory=list)
    link_issues: dict[str, Any] = field(default_factory=dict)


class WikiEngine(Plugin):
    """
    Coda Knowledge Engine V6.1 — 插件化统一入口。
    
    作为 AgentEngine 的主插件运行，并管理其内部的 14+ 子插件。
    """
    name = "wiki_engine"

    def __init__(self, config: WikiEngineConfig):
        self._config = config
        self._wiki_dir = Path(config.wiki_dir).resolve()
        self._agent_id = config.agent_id

        # ── Core Services Hub ──
        self.registry_hub = WikiPluginRegistry(
            ctx_factory=lambda: WikiPluginContext(str(self._wiki_dir), self.registry_hub, self._config)
        )

        # ── Facade Accessors (Late Bound via Registry) ──
        # These will be populated in initialize() after discovery
        self.storage: Optional[WikiStorage] = None
        self.atlas: Optional[AtlasIndex] = None
        self.compiler: Optional[MemoryCompiler] = None
        self.search: Optional[WikiSearchEngine] = None
        self.pii: Optional[PIISentinel] = None
        self.shadow: Optional[ShadowMirror] = None
        self.ripple: Optional[RippleEngine] = None
        self.session: Optional[SessionLifecycle] = None
        self.doctor: Optional[WikiDoctor] = None
        self.skills: Optional[SkillTracker] = None
        self.claiming: Optional[StepClaiming] = None
        self.governance: GovernanceEngine = GovernanceEngine()
        self.para: Optional[PARAClassifier] = None
        self.distiller: Optional[KnowledgeDistiller] = None
        self.chunker: Optional[ASTChunker] = None
        self.link_resolver: Optional[MultiPassLinkResolver] = None
        self.context_tree: Optional[ContextTree] = None
        self.maturity: Optional[MaturityModel] = None
        self.conflict_detector: Optional[ConflictDetector] = None
        self.gap_analyzer: Optional[GapAnalyzer] = None
        self.cross_domain: Optional[CrossDomainDiscovery] = None
        self.moc_generator: Optional[MOCGenerator] = None
        self.explorer: Optional[ActiveExplorer] = None
        self.handoff: Optional[HandoffManager] = None
        self.agent_reg: Optional[AgentRegistry] = None # renamed from registry to avoid collision
        self.barrier: Optional[TaskBarrier] = None
        self.memory_iso: Optional[MemoryIsolation] = None
        self.deferral: Optional[DeferralMonitor] = None
        self.retry_queue: Optional[RetryQueue] = None
        self.audit: Optional[AuditTrail] = None
        self.polyglot: Optional[PolyglotParser] = None
        self.crystallizer: Optional[Crystallizer] = None
        self.dream_cycle: Optional[DreamCycleService] = None

        # ── Embedder (late-bound) ──
        self._embedder: Any = None
        self._embed_fn: Callable[[list[str]], list[list[float]]] | None = None

        self._initialized = False
        logger.info(f"📚 WikiEngine created for: {self._wiki_dir}")

    # ════════════════════════════════════════
    #  Lifecycle
    # ════════════════════════════════════════

    async def initialize(self) -> None:
        """
        初始化所有子系统并通过引擎内部插件注册表加载全部 14+ 模块。
        """
        # [V7.1 Hardened] 确保统一 LLM 服务已注册
        llm = self.registry_hub.get_service("llm")
        if not llm:
            model = get_secret("DEFAULT_MODEL_NAME", "gemini-3-flash-agent")
            logger.info(f"🔮 WikiEngine: Initializing default unified LLM service ({model})")
            llm = create_caller(model)
            self.registry_hub.register_service("llm", llm)
            
        embedder = self._embedder
        start = time.time()
        
        # 1. 设置插件目录
        plugins_dir = Path(__file__).parent / "plugins"
        
        # 2. 动态并行加载所有子插件
        await self.registry_hub.discover_and_register(plugins_dir)
        
        # 3. 提取核心服务引用以维持向后兼容的门面 API
        self.storage = self.registry_hub.get_plugin("storage")
        self.atlas = self.registry_hub.get_plugin("atlas")
        self.compiler = self.registry_hub.get_plugin("compiler")
        self.search = self.registry_hub.get_plugin("search")
        self.pii = self.registry_hub.get_plugin("pii")
        self.shadow = self.registry_hub.get_plugin("shadow")
        self.ripple = self.registry_hub.get_plugin("ripple")
        self.session = self.registry_hub.get_plugin("session")
        self.doctor = self.registry_hub.get_plugin("doctor")
        self.skills = self.registry_hub.get_plugin("skill_tracker")
        self.claiming = self.registry_hub.get_plugin("step_claiming")
        self.governance = self.registry_hub.get_plugin("governance")
        self.para = self.registry_hub.get_plugin("para")
        self.distiller = self.registry_hub.get_plugin("distiller")
        self.chunker = self.registry_hub.get_plugin("chunker")
        self.link_resolver = self.registry_hub.get_plugin("link_resolver")
        self.context_tree = self.registry_hub.get_plugin("context_tree")
        self.maturity = self.registry_hub.get_plugin("maturity")
        self.conflict_detector = self.registry_hub.get_plugin("conflict")
        self.gap_analyzer = self.registry_hub.get_plugin("gap_analyzer")
        self.cross_domain = self.registry_hub.get_plugin("discovery")
        self.moc_generator = self.registry_hub.get_plugin("moc_generator")
        self.explorer = self.registry_hub.get_plugin("explorer")
        self.handoff = self.registry_hub.get_plugin("handoff")
        self.agent_reg = self.registry_hub.get_plugin("agent_registry")
        self.barrier = self.registry_hub.get_plugin("barrier")
        self.memory_iso = self.registry_hub.get_plugin("memory_isolation")
        self.deferral = self.registry_hub.get_plugin("deferral_monitor")
        self.retry_queue = self.registry_hub.get_plugin("retry_queue")
        self.audit = self.registry_hub.get_plugin("audit")
        self.polyglot = self.registry_hub.get_plugin("polyglot_parser")
        self.crystallizer = self.registry_hub.get_plugin("crystallizer")
        self.dream_cycle = self.registry_hub.get_plugin("dream_cycle")

        # 4. 注册核心服务模块供插件间调用
        self.registry_hub.register_service("storage", self.storage)
        self.registry_hub.register_service("atlas", self.atlas)
        self.registry_hub.register_service("manifest", getattr(self.storage, "manifest", None))
        
        # [V7.0] 注册 LLM 服务
        if llm:
            self.registry_hub.register_service("llm", llm)
        
        # 5. 绑定 Embedder (如果提供)
        if embedder is not None:
            self._embedder = embedder
            self._embed_fn = embedder.encode
            if self.atlas:
                self.atlas.set_embed_fn(embedder.encode)
        
        # 6. 执行所有插件的初始化 (Dependency Injection 注入)
        ctx = self.registry_hub._ctx_factory()
        for p_name, plugin in self.registry_hub._plugins.items():
            try:
                await plugin.initialize(ctx)
            except Exception as e:
                logger.error(f"Failed to initialize plugin {p_name}: {e}")

        # 6.5 重新注册可能在 initialize 中延迟生成的服务 (如 manifest)
        self.registry_hub.register_service("manifest", getattr(self.storage, "manifest", None))
                
        await self.registry_hub.dispatch(WikiHook.ON_INITIALIZE)

        # 7. 注册自身心跳 ( coordination 现在是插件)
        if self.agent_reg:
            self.agent_reg.register(AgentHeartbeat(
                agent_id=self._agent_id,
                status="active",
                role="wiki_engine",
                current_task="initialization",
            ))

        if self.audit:
            self.audit.log("ingest", "initialization", f"WikiEngine V6.1 (Pluginized) initialized in {time.time()-start:.2f}s")

        self._initialized = True
        self._current_session_id: Optional[str] = None
    
    async def on_packet(self, packet: UniversalCognitivePacket) -> UniversalCognitivePacket | None:
        """主引擎数据包转发。"""
        # 如果是查询包，转发给查询逻辑，如果是管理包，处理配置变更
        return None

    async def health_check(self) -> bool:
        """检查 Atlas 与 Storage 是否健康。"""
        return self._initialized and self.atlas is not None

    # ════════════════════════════════════════
    #  Compilation Pipeline (Full Orchestration)
    # ════════════════════════════════════════

    async def compile(self, full: bool = True) -> CompileResult:
        """
        完整编译流水线 (编排所有子系统):
          1. 影子镜像更新 (二进制 → Markdown)
          2. PII 海关 (隐私脱敏)
          3. 编译 (解析 + 索引)
          4. 多轮链接解析
          5. 冲突检测
          6. 知识蒸馏
          7. 审计
        """
        result = CompileResult()
        overall_start = time.time()

        # 心跳更新
        if self.agent_reg:
            self.agent_reg.heartbeat(self._agent_id)

        # ── Step 1: Shadow Mirroring ──
        if self._config.enable_shadows:
            try:
                raw_dir = self._wiki_dir / "raw"
                if raw_dir.exists():
                    shadow_count = 0
                    shadow_result = None
                    for f in raw_dir.rglob("*"):
                        if f.suffix.lower() in {".pdf", ".xlsx", ".xls", ".csv", ".png", ".jpg"}:
                            if self.shadow:
                                shadow_result = self.shadow.create_shadow(f)
                            if shadow_result:
                                shadow_count += 1
                    if shadow_count > 0:
                        logger.info(f"🪞 Shadow mirrors: {shadow_count} binary files processed")
            except Exception as e:
                logger.warning(f"Shadow mirroring skipped: {e}")

        # ── Step 2: Core Compilation ──
        try:
            if self.compiler:
                if full:
                    stats = await self.compiler.compile_full()
                else:
                    stats = await self.compiler.compile_incremental()
            else:
                stats = {}

            result.files_processed = stats.get("ingested", 0)
            result.nodes_indexed = stats.get("indexed", 0)
            result.nodes_deleted = stats.get("deleted", 0)
            result.errors = stats.get("errors", 0)
        except Exception as e:
            logger.error(f"Compilation failed: {e}")
            if self.retry_queue:
                self.retry_queue.enqueue(RetryEntry(
                    f"compile_{int(time.time())}",
                    "compile",
                    str(self._wiki_dir),
                    error=str(e),
                ))
            result.errors += 1

        # ── Step 3: Multi-Pass Link Resolution ──
        try:
            if self.link_resolver:
                link_report = self.link_resolver.resolve(max_passes=3)
                result.link_issues = link_report
            if self.atlas:
                result.relations_extracted = self.atlas.get_stats().get("relation_count", 0)
        except Exception as e:
            logger.warning(f"Link resolution skipped: {e}")

        # ── Step 4: Conflict Detection ──
        try:
            if self.conflict_detector:
                result.conflicts = self.conflict_detector.detect_all()
            if result.conflicts:
                logger.warning(f"⚠️ {len(result.conflicts)} conflicts detected")
        except Exception as e:
            logger.warning(f"Conflict detection skipped: {e}")

        result.compile_time = round(time.time() - overall_start, 3)

        # ── Step 5: Audit ──
        self.audit.log(
            "compile",
            "full" if full else "incremental",
            f"Processed {result.files_processed} files, "
            f"indexed {result.nodes_indexed}, "
            f"errors {result.errors}, "
            f"conflicts {len(result.conflicts)}, "
            f"time {result.compile_time}s",
            agent_id=self._agent_id,
        ) if self.audit else None

        return result

    # ════════════════════════════════════════
    #  §13.5 后台知识收割 (Background Closeout)
    # ════════════════════════════════════════

    async def background_closeout(
        self,
        transcript: list[dict[str, str]] | None = None,
        learnings_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """
        会话后蒸馏 — 扫描 Transcript 提取可复用知识资产。
        无需人类干预即可完成知识积累。
        """
        if not transcript:
            return {"extracted": 0, "skipped": True}

        extracted_learnings: list[str] = []

        for msg in transcript:
            content = str(msg.get("content", ""))
            role = msg.get("role", "")

            # 只处理助手的长回复 (有实质内容)
            if role != "assistant" or len(content) < 200:
                continue

            # 提取关键决策和发现
            # 检测 "因为/决定/发现/学到/注意" 等触发词
            trigger_patterns = [
                r'(?:因为|由于|原因是|根因|root cause)[：:]\s*(.{20,200})',
                r'(?:决定|选择|采用|使用)[了]?\s*(.{10,150})',
                r'(?:发现|注意到|观察到|确认)[了]?\s*(.{10,200})',
                r'(?:关键发现|key finding|关键结论)[：:]\s*(.{20,200})',
            ]

            import re
            for pattern in trigger_patterns:
                matches = re.findall(pattern, content)
                extracted_learnings.extend(matches[:3])  # 每种最多 3 条

        if not extracted_learnings or not learnings_path:
            return {"extracted": len(extracted_learnings), "path": None}

        # 写入 LEARNINGS.md (供人类快速阅读)
        path = Path(learnings_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        time_str = time.strftime("%Y-%m-%d %H:%M")

        entry = f"\n## [{time_str}] Session Closeout\n"
        for learning in extracted_learnings[:10]:
            entry += f"- {learning.strip()}\n"
        entry += "\n"

        with open(path, "a", encoding="utf-8") as f:
            f.write(entry)

        # ── 强化写入 (Reinforced Writing) ──
        # 自动将发现转化为结构化知识，反哺给联邦图谱
        if self.compiler and len(extracted_learnings) > 0:
            synthesis_dir = self._wiki_dir / "synthesis"
            synthesis_dir.mkdir(parents=True, exist_ok=True)
            
            # 创建反哺节点，利用 AKP 规范
            node_id = f"akp-learning-{timestamp}"
            md_content = f"""---
title: Session Learnings {time_str}
type: synthesis
status: drafted
confidence: 0.9
epistemic_tag: empirical
authority: L2
---

# Session Learnings {time_str}

Autonomously extracted knowledge from the recent session.

## Core Discoveries
"""
            for learning in extracted_learnings[:10]:
                md_content += f"- {learning.strip()}\n"
                
            md_path = synthesis_dir / f"{node_id}.md"
            md_path.write_text(md_content, encoding="utf-8")
            
            # 增量编译 (将其打入本地图谱与联邦图谱)
            logger.info("🧠 Triggering Reinforced Writing ingestion for new learnings...")
            try:
                if self.compiler:
                    await self.compiler.compile_incremental()
            except Exception as e:
                logger.error(f"Failed to ingest learnings: {e}")

        if self.audit:
            self.audit.log("synthesize", str(path), f"Extracted {len(extracted_learnings)} learnings & triggered ingestion")

        return {
            "extracted": len(extracted_learnings),
            "path": str(path),
        }

    # ════════════════════════════════════════
    #  Search & Query API
    # ════════════════════════════════════════

    async def query(
        self, q: str, top_k: int = 10, embed_fn: Callable[..., Any] | None = None
    ) -> list[dict[str, Any]]:
        """统一搜索接口。"""
        from .plugins.search import SearchQuery
        sq = SearchQuery(text=q, top_k=top_k)
        
        # 为了兼容向后返回字典列表
        if not self.search:
            return []
        results = await self.search.search(sq)
        return [r.meta for r in results]

    async def ask(self, question: str) -> dict[str, Any]:
        """Boolean Ask (证据门控)。"""
        if not self.search:
            return {"answer": False, "confidence": 0.0, "supporting_evidence": [], "contradicting_evidence": []}
        res = await self.search.boolean_ask(question, threshold=0.6)
        if hasattr(res, "to_dict"):
            return res.to_dict()
        return vars(res) if not isinstance(res, dict) else res

    async def get_llm_context(
        self, query: str, max_tokens: int = 4000
    ) -> str:
        """获取 LLM 就绪的检索上下文。"""
        # Note: here we perform querying via WikiSearchEngine
        if not self.search:
            return ""
        from .plugins.search import SearchQuery
        sq = SearchQuery(text=query, top_k=10)
        results = await self.search.search(sq)
        return self.search.build_llm_context(results, max_tokens=max_tokens)

    # ════════════════════════════════════════
    #  Intelligence API
    # ════════════════════════════════════════

    def get_maturity(self) -> MaturityScore:
        """获取知识库成熟度评分。"""
        if not self.maturity or not self.atlas:
            return MaturityScore(overall=0.0)
        return self.maturity.evaluate(self.atlas)

    def get_gaps(self) -> list[CognitiveGap]:
        """获取认知空洞。"""
        return self.gap_analyzer.analyze() if self.gap_analyzer else []

    def get_conflicts(self) -> list[ConflictDetection]:
        """获取冲突列表。"""
        return self.conflict_detector.detect_all() if self.conflict_detector else []

    def get_bridges(self) -> list[CrossDomainBridge]:
        """获取跨领域桥接。"""
        return self.cross_domain.find_bridges() if self.cross_domain else []

    def get_exploration_agenda(self) -> dict[str, Any]:
        """获取探索议程。"""
        return self.explorer.generate_exploration_agenda() if self.explorer else {}

    def generate_moc(self, category: str | None = None) -> str:
        """生成内容地图。"""
        return self.moc_generator.generate_moc(category) if self.moc_generator else ""

    def get_deferred_tasks(self) -> list[Any]:
        """获取延期任务。"""
        return self.deferral.scan_directory(self._wiki_dir) if self.deferral else []

    # ════════════════════════════════════════
    #  Diagnostics
    # ════════════════════════════════════════

    def diagnose(self) -> list[dict[str, Any]]:
        """运行 Wiki Doctor 诊断。"""
        res = self.doctor.diagnose() if self.doctor else []
        return [d.to_dict() if hasattr(d, "to_dict") else vars(d) for d in res]

    def get_dashboard(self) -> dict[str, Any]:
        """生成综合状态面板。"""
        stats = self.atlas.get_stats() if self.atlas else {}
        maturity = self.get_maturity()
        retry_stats = self.retry_queue.get_stats() if self.retry_queue else {}
        online_agents = self.agent_reg.list_online() if self.agent_reg else []

        return {
            "knowledge": {
                "nodes": stats.get("node_count", 0),
                "relations": stats.get("relation_count", 0),
                "types": stats.get("type_distribution", {}),
                "statuses": stats.get("status_distribution", {}),
            },
            "maturity": {
                "grade": maturity.grade,
                "score": maturity.overall,
                "dimensions": maturity.dimensions,
                "recommendations": maturity.recommendations[:3],
            },
            "health": {
                "diagnostics": len(self.doctor.diagnose()) if self.doctor else 0,
                "retry_queue": retry_stats,
            },
            "coordination": {
                "online_agents": len(online_agents),
                "agents": [a.agent_id for a in online_agents],
            },
        }

    # ════════════════════════════════════════
    #  Coordination API
    # ════════════════════════════════════════

    def create_handoff(
        self,
        task_id: str,
        completed: list[str],
        next_steps: list[str],
        findings: list[str] | None = None,
        modified_files: list[str] | None = None,
    ) -> Path:
        """创建任务交接包。"""
        packet = HandoffPacket(
            task_id=task_id,
            agent_id=self._agent_id,
            completed_items=completed,
            next_steps=next_steps,
            key_findings=findings or [],
            modified_files=modified_files or [],
        )
        if not self.handoff:
            return Path()
        path = self.handoff.create_handoff(packet)
        if self.audit:
            self.audit.log("handoff", task_id, f"Created handoff with {len(completed)} completed items")
        return path

    def consume_handoff(self) -> HandoffPacket | None:
        """消费最新的交接包。"""
        return self.handoff.consume_latest(self._agent_id) if self.handoff else None

    # ════════════════════════════════════════
    #  AgentEngine Integration Hooks
    # ════════════════════════════════════════

    async def on_session_start(self, session_id: str) -> dict[str, Any]:
        """
        AgentEngine 会话开始钩子。
        执行 RA-H 导向、加载 MOC、检查延期任务。
        """
        self._current_session_id = session_id
        orientation = self.session.on_session_start(session_id) if self.session else {}
        deferred = self.get_deferred_tasks()

        if self.agent_reg:
            self.agent_reg.heartbeat(self._agent_id)
        if self.audit:
            self.audit.log("ingest", "session_start", f"Session {session_id} started")

        return {
            "orientation": orientation,
            "deferred_tasks": len(deferred),
            "deferred_urgent": [d for d in deferred if d.escalation.value == "force"],
        }

    async def on_session_end(self, session_id: str | None = None, transcript: list[dict[str, str]] | None = None) -> dict[str, Any]:
        """
        AgentEngine 会话结束钩子。
        执行后台收割、生成交接包、更新心跳。
        """
        sid = session_id or self._current_session_id or "unknown"
        # 后台知识收割
        closeout = await self.background_closeout(
            transcript=transcript,
            learnings_path=self._wiki_dir / "LEARNINGS.md",
        )

        # 生成交接包
        handoff_data = self.session.on_session_end() if self.session else None

        # 更新心跳为空闲
        if self.agent_reg:
            self.agent_reg.register(AgentHeartbeat(
                agent_id=self._agent_id,
                status="idle",
                role="wiki_engine",
                current_task="",
                session_id=sid,
            ))

        if self.audit:
            self.audit.log("handoff", "session_end", f"Session {sid} ended. Extracted {closeout.get('extracted', 0)} learnings.")

        return {
            "closeout": closeout,
            "handoff": handoff_data.to_dict() if handoff_data else None,
        }

    async def on_idle(self) -> dict[str, Any]:
        """
        AgentEngine 空闲钩子 — 自动维护。
        执行漂移检测、孤儿扫描、重试队列处理。
        """
        results: dict[str, Any] = {}

        # 1. 漂移检测
        try:
            raw_dir = self._wiki_dir / "raw"
            if raw_dir.exists() and self.atlas:
                drift = self.atlas.detect_drift(raw_dir)
                if drift["orphaned_in_index"] or drift["missing_in_index"]:
                    results["drift"] = drift
                    logger.info(f"🔍 Drift: {len(drift['orphaned_in_index'])} orphaned, {len(drift['missing_in_index'])} missing")
        except Exception as e:
            logger.warning(f"Drift detection skipped: {e}")

        # 2. 重试队列处理
        if not self.retry_queue:
            return results
        ready = self.retry_queue.get_ready_entries()
        if ready:
            results["retries_pending"] = len(ready)
            for entry in ready[:3]:  # 每次最多处理 3 个
                try:
                    if entry.action == "compile" and self.compiler:
                        await self.compiler.compile_incremental()
                        self.retry_queue.mark_success(entry.id)
                    else:
                        logger.warning(f"Unknown retry action: {entry.action}")
                except Exception as e:
                    self.retry_queue.mark_failed(entry, str(e))

        # 3. 统计汇总
        if self.compiler:
            results["compiler"] = self.compiler.get_stats()

        # 4. 心跳更新
        if self.agent_reg:
            self.agent_reg.heartbeat(self._agent_id)

        return results

    async def shutdown(self) -> None:
        """优雅关闭。"""
        if self.agent_reg:
            self.agent_reg.unregister(self._agent_id)
        if self.atlas:
            self.atlas.close()
        if self.audit:
            self.audit.log("archive", "shutdown", "WikiEngine shutting down")
        logger.info("🛑 WikiEngine shut down gracefully")
