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
from typing import Any, Callable

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
    KnowledgeDistiller,
    ASTChunker,
    MultiPassLinkResolver,
    ContextTree,
    MaturityModel, MaturityScore,
)

logger = logging.getLogger("Coda.wiki.engine")


@dataclass
class WikiEngineConfig:
    """Wiki 引擎配置。"""
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


@dataclass
class CompileResult:
    """编译结果摘要。"""
    files_processed: int = 0
    nodes_indexed: int = 0
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
            ctx_factory=lambda: WikiPluginContext(self._wiki_dir, self.registry_hub, self._config)
        )

        # ── Facade Accessors (Late Bound via Registry) ──
        # These will be populated in initialize() after discovery
        self.storage: WikiStorage = None
        self.atlas: AtlasIndex = None
        self.compiler: MemoryCompiler = None
        self.search: WikiSearchEngine = None
        self.pii: PIISentinel = None
        self.shadow: ShadowMirror = None
        self.ripple: RippleEngine = None
        self.session: SessionLifecycle = None
        self.doctor: WikiDoctor = None
        self.skills: SkillTracker = None
        self.claiming: StepClaiming = None
        self.governance: GovernanceEngine = GovernanceEngine()
        self.para: PARAClassifier = None
        self.distiller: KnowledgeDistiller = None
        self.chunker: ASTChunker = None
        self.link_resolver: MultiPassLinkResolver = None
        self.context_tree: ContextTree = None
        self.maturity: MaturityModel = None
        self.conflict_detector: ConflictDetector = None
        self.gap_analyzer: GapAnalyzer = None
        self.cross_domain: CrossDomainDiscovery = None
        self.moc_generator: MOCGenerator = None
        self.explorer: ActiveExplorer = None
        self.handoff: HandoffManager = None
        self.agent_reg: AgentRegistry = None # renamed from registry to avoid collision
        self.barrier: TaskBarrier = None
        self.memory_iso: MemoryIsolation = None
        self.deferral: DeferralMonitor = None
        self.retry_queue: RetryQueue = None
        self.audit: AuditTrail = None
        self.polyglot: PolyglotParser = None

        # ── Embedder (late-bound) ──
        self._embedder: Any = None
        self._embed_fn: Callable[[list[str]], list[list[float]]] | None = None

        self._initialized = False
        logger.info(f"📚 WikiEngine created for: {self._wiki_dir}")

    # ════════════════════════════════════════
    #  Lifecycle
    # ════════════════════════════════════════

    async def initialize(self, embedder: Any = None) -> dict[str, Any]:
        """
        初始化所有子系统并通过引擎内部插件注册表加载全部 14+ 模块。
        """
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

        # 4. 注册核心服务模块供插件间调用
        self.registry_hub.register_service("storage", self.storage)
        self.registry_hub.register_service("atlas", self.atlas)
        self.registry_hub.register_service("manifest", getattr(self.storage, "manifest", None))
        
        # 5. 绑定 Embedder (如果提供)
        if embedder is not None:
            self._embedder = embedder
            self._embed_fn = embedder.encode
            if self.atlas:
                self.atlas.set_embed_fn(embedder.encode)
        
        # 6. 执行所有插件的初始化钩子 (Dependency Injection 注入)
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
        return {
            "status": "online",
            "plugins_loaded": len(self.registry_hub._plugins),
            "vec_enabled": self.atlas.vec_enabled if self.atlas else False,
            "init_time": round(time.time() - start, 2),
        }
    
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

    def compile(self, full: bool = True) -> CompileResult:
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
                    for f in raw_dir.rglob("*"):
                        if f.suffix.lower() in {".pdf", ".xlsx", ".xls", ".csv", ".png", ".jpg"}:
                            shadow_result = self.shadow.create_shadow(f)
                            if shadow_result:
                                shadow_count += 1
                    if shadow_count > 0:
                        logger.info(f"🪞 Shadow mirrors: {shadow_count} binary files processed")
            except Exception as e:
                logger.warning(f"Shadow mirroring skipped: {e}")

        # ── Step 2: Core Compilation ──
        try:
            if full:
                stats = self.compiler.compile_full()
            else:
                stats = self.compiler.compile_incremental()

            result.files_processed = stats.get("ingested", 0)
            result.nodes_indexed = stats.get("indexed", 0)
            result.errors = stats.get("errors", 0)
        except Exception as e:
            logger.error(f"Compilation failed: {e}")
            self.retry_queue.enqueue(RetryEntry(
                id=f"compile_{int(time.time())}",
                action="compile",
                target=str(self._wiki_dir),
                error=str(e),
            ))
            result.errors += 1

        # ── Step 3: Multi-Pass Link Resolution ──
        try:
            link_report = self.link_resolver.resolve(max_passes=3)
            result.link_issues = link_report
            result.relations_extracted = self.atlas.get_stats().get("relation_count", 0)
        except Exception as e:
            logger.warning(f"Link resolution skipped: {e}")

        # ── Step 4: Conflict Detection ──
        try:
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
        )

        return result

    # ════════════════════════════════════════
    #  §13.5 后台知识收割 (Background Closeout)
    # ════════════════════════════════════════

    def background_closeout(
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

        # 写入 LEARNINGS.md
        path = Path(learnings_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y-%m-%d %H:%M")

        entry = f"\n## [{timestamp}] Session Closeout\n"
        for learning in extracted_learnings[:10]:
            entry += f"- {learning.strip()}\n"
        entry += "\n"

        with open(path, "a", encoding="utf-8") as f:
            f.write(entry)

        self.audit.log("synthesize", str(path), f"Extracted {len(extracted_learnings)} learnings")

        return {
            "extracted": len(extracted_learnings),
            "path": str(path),
        }

    # ════════════════════════════════════════
    #  Search & Query API
    # ════════════════════════════════════════

    def query(
        self, q: str, top_k: int = 10, embed_fn: Callable[..., Any] | None = None
    ) -> list[dict[str, Any]]:
        """统一搜索接口。"""
        fn = embed_fn or self._embed_fn
        return self.search.search(q, top_k=top_k, embed_fn=fn)

    def ask(self, question: str,) -> dict[str, Any]:
        """Boolean Ask (证据门控)。"""
        return self.search.boolean_ask(question, embed_fn=self._embed_fn)

    def get_llm_context(
        self, query: str, max_tokens: int = 4000
    ) -> str:
        """为 LLM 组装上下文。"""
        return self.search.assemble_llm_context(query, embed_fn=self._embed_fn, max_tokens=max_tokens)

    # ════════════════════════════════════════
    #  Intelligence API
    # ════════════════════════════════════════

    def get_maturity(self) -> MaturityScore:
        """获取知识库成熟度评分。"""
        return self.maturity.evaluate(self.atlas)

    def get_gaps(self) -> list[CognitiveGap]:
        """获取认知空洞。"""
        return self.gap_analyzer.analyze()

    def get_conflicts(self) -> list[ConflictDetection]:
        """获取冲突列表。"""
        return self.conflict_detector.detect_all()

    def get_bridges(self) -> list[CrossDomainBridge]:
        """获取跨领域桥接。"""
        return self.cross_domain.find_bridges()

    def get_exploration_agenda(self) -> dict[str, Any]:
        """获取探索议程。"""
        return self.explorer.generate_exploration_agenda()

    def generate_moc(self, category: str | None = None) -> str:
        """生成内容地图。"""
        return self.moc_generator.generate_moc(category)

    def get_deferred_tasks(self) -> list[Any]:
        """获取延期任务。"""
        return self.deferral.scan_directory(self._wiki_dir)

    # ════════════════════════════════════════
    #  Diagnostics
    # ════════════════════════════════════════

    def diagnose(self) -> list[dict[str, Any]]:
        """运行 Wiki Doctor 诊断。"""
        return self.doctor.diagnose()

    def get_dashboard(self) -> dict[str, Any]:
        """生成综合状态面板。"""
        stats = self.atlas.get_stats()
        maturity = self.get_maturity()
        retry_stats = self.retry_queue.get_stats()
        online_agents = self.registry.list_online()

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
                "diagnostics": len(self.doctor.diagnose()),
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
        path = self.handoff.create_handoff(packet)
        self.audit.log("handoff", task_id, f"Created handoff with {len(completed)} completed items")
        return path

    def consume_handoff(self) -> HandoffPacket | None:
        """消费最新的交接包。"""
        return self.handoff.consume_latest(self._agent_id)

    # ════════════════════════════════════════
    #  AgentEngine Integration Hooks
    # ════════════════════════════════════════

    def on_session_start(self, session_id: str) -> dict[str, Any]:
        """
        AgentEngine 会话开始钩子。
        执行 RA-H 导向、加载 MOC、检查延期任务。
        """
        orientation = self.session.on_session_start(session_id)
        deferred = self.get_deferred_tasks()

        self.registry.heartbeat(self._agent_id)
        self.audit.log("ingest", "session_start", f"Session {session_id} started")

        return {
            "orientation": orientation,
            "deferred_tasks": len(deferred),
            "deferred_urgent": [d for d in deferred if d.escalation.value == "force"],
        }

    def on_session_end(self, session_id: str, transcript: list[dict[str, str]] | None = None) -> dict[str, Any]:
        """
        AgentEngine 会话结束钩子。
        执行后台收割、生成交接包、更新心跳。
        """
        # 后台知识收割
        closeout = self.background_closeout(
            transcript=transcript,
            learnings_path=self._wiki_dir / "LEARNINGS.md",
        )

        # 生成交接包
        handoff_data = self.session.on_session_end(session_id)

        # 更新心跳为空闲
        if self.agent_reg:
            self.agent_reg.register(AgentHeartbeat(
                agent_id=self._agent_id,
                status="idle",
                role="wiki_engine",
                current_task="",
                session_id=session_id,
            ))

        if self.audit:
            self.audit.log("handoff", "session_end", f"Session {session_id} ended. Extracted {closeout.get('extracted', 0)} learnings.")

        return {
            "closeout": closeout,
            "handoff": handoff_data,
        }

    def on_idle(self) -> dict[str, Any]:
        """
        AgentEngine 空闲钩子 — 自动维护。
        执行漂移检测、孤儿扫描、重试队列处理。
        """
        results: dict[str, Any] = {}

        # 1. 漂移检测
        try:
            raw_dir = self._wiki_dir / "raw"
            if raw_dir.exists():
                drift = self.atlas.detect_drift(raw_dir)
                if drift["orphaned"] or drift["missing"]:
                    results["drift"] = drift
                    logger.info(f"🔍 Drift: {len(drift['orphaned'])} orphaned, {len(drift['missing'])} missing")
        except Exception as e:
            logger.warning(f"Drift detection skipped: {e}")

        # 2. 重试队列处理
        ready = self.retry_queue.get_ready_entries()
        if ready:
            results["retries_pending"] = len(ready)
            for entry in ready[:3]:  # 每次最多处理 3 个
                try:
                    if entry.action == "compile":
                        self.compiler.compile_incremental()
                        self.retry_queue.mark_success(entry.id)
                    else:
                        logger.warning(f"Unknown retry action: {entry.action}")
                except Exception as e:
                    self.retry_queue.mark_failed(entry, str(e))

        # 3. 心跳更新
        if self.agent_reg:
            self.agent_reg.heartbeat(self._agent_id)

        return results

    def shutdown(self) -> None:
        """优雅关闭。"""
        if self.agent_reg:
            self.agent_reg.unregister(self._agent_id)
        if self.atlas:
            self.atlas.close()
        if self.audit:
            self.audit.log("archive", "shutdown", "WikiEngine shutting down")
        logger.info("🛑 WikiEngine shut down gracefully")
