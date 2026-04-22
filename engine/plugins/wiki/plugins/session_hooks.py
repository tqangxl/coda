"""
Coda Knowledge Engine V6.0 — Session Hooks & Wiki Doctor
会话生命周期管理 + Wiki 诊断与自愈。

Session Hooks:
  - onStart: getContext 强制调用 (RA-H Orientation)
  - onIdle: 定时漂移检测、孤儿扫描
  - onEnd: 经验蒸馏、知识固化
  - contextInjection: MOC 导航 + 激活衰减

Doctor Wiki:
  - Index-File 一致性审计 (Drift Detection)
  - 承重边失效分析
  - FTS/Vector 健康检查
  - 编译流水线修复
"""

from __future__ import annotations

from ..base_plugin import WikiPlugin, WikiHook, WikiPluginContext

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..akp_types import (
    KnowledgeNode, ConflictReport, HandoffSlice,
    AuditLogEntry, SessionCheckpoint,
)
from .atlas import AtlasIndex
from .storage import WikiStorage, CompilationManifest

logger = logging.getLogger("Coda.wiki.session")


# ════════════════════════════════════════════
#  Session Lifecycle Manager
# ════════════════════════════════════════════

class SessionLifecycle(WikiPlugin):
    """
    会话生命周期管理器。
    """
    name = "session"

    def __init__(
        self,
        atlas: AtlasIndex | None = None,
        storage: WikiStorage | None = None,
        manifest: CompilationManifest | None = None,
    ):
        self._atlas = atlas
        self._storage = storage
        self._manifest = manifest
        self._hooks: dict[str, list[Callable[..., Any]]] = {
            "on_start": [],
            "on_idle": [],
            "on_end": [],
            "on_query": [],
        }
        self._session_start: float = 0.0
        self._query_count: int = 0
        self._context_injected: bool = False
        self._checkpoint_threshold: int = 5  # 每 5 次查询触发一次物理断点
        self._checkpoint_counter: int = 0

    async def initialize(self, ctx: WikiPluginContext) -> None:
        """插件初始化入口。"""
        if not self._atlas:
            self._atlas = ctx.atlas
        if not self._storage:
            self._storage = ctx.storage
        if not self._manifest:
            self._manifest = ctx.manifest
        logger.info("🕒 Session Lifecycle plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        """响应 Wiki 钩子。"""
        if hook == WikiHook.SESSION_START:
            return self.on_session_start(payload or "")
        elif hook == WikiHook.IDLE:
            return self.on_session_idle()
        elif hook == WikiHook.SESSION_END:
            return self.on_session_end(payload)
        return None

    def register_hook(self, phase: str, hook: Callable[..., Any]) -> None:
        if phase in self._hooks:
            self._hooks[phase].append(hook)

    def on_session_start(self, session_id: str = "") -> dict[str, Any]:
        """
        会话开始 (RA-H Orientation Pattern)。

        强制调用 getContext 工具:
        1. 加载 Wiki 统计概览
        2. 获取 MOC (Map of Content) 导航
        3. 恢复断点 (如果有)
        4. 刷新激活衰减
        """
        self._session_start = time.time()
        self._query_count = 0

        context: dict[str, Any] = {}

        # ── 1. Wiki 统计概览 ──
        try:
            if self._atlas:
                stats = self._atlas.get_stats()
                context["wiki_stats"] = stats
            else:
                context["wiki_stats"] = {"node_count": 0, "error": "Atlas not initialized"}
        except Exception as e:
            context["wiki_stats_error"] = str(e)

        # ── 2. MOC 导航 ──
        context["moc"] = self._build_moc()

        # ── 3. 恢复断点 ──
        if self._storage:
            pending = self._storage.load_pending_writes()
            if pending:
                context["pending_writes"] = len(pending)
                context["pending_detail"] = [p.get("_pending_file", "") for p in pending[:5]]

        # ── 4. 激活衰减 ──
        self._apply_global_decay()

        # ── 5. 执行注册的 on_start 钩子 ──
        for hook in self._hooks.get("on_start", []):
            try:
                hook(context)
            except Exception as e:
                logger.warning(f"on_start hook failed: {e}")

        self._context_injected = True
        if self._storage:
            self._storage.append_audit_log(
                action="session_start",
                detail=f"Nodes: {context.get('wiki_stats', {}).get('node_count', 0)}",
            )

        return context

    def on_session_idle(self) -> dict[str, Any]:
        """
        会话空闲期间的后台维护。
        """
        results: dict[str, Any] = {}

        # ── 漂移检测 ──
        try:
            if self._atlas and self._storage and hasattr(self._atlas, "detect_drift"):
                drift = self._atlas.detect_drift(self._storage._root / "knowledge")
                results["drift"] = drift
                orphaned_count = len(drift.get("orphaned_in_index", []))
                missing_count = len(drift.get("missing_in_index", []))
                if orphaned_count > 0 or missing_count > 0:
                    logger.warning(
                        f"⚠️ Drift detected: {orphaned_count} orphaned in index, "
                        f"{missing_count} missing in index"
                    )
        except Exception as e:
            results["drift_error"] = str(e)

        # ── 孤儿页面扫描 ──
        try:
            if self._atlas and hasattr(self._atlas, "find_orphans"):
                orphans = self._atlas.find_orphans()
                results["orphan_pages"] = len(orphans)
                if orphans:
                    results["orphan_sample"] = [o["title"] for o in orphans[:5]]
        except Exception as e:
            results["orphan_error"] = str(e)

        # ── Wanted Pages ──
        try:
            if self._atlas and hasattr(self._atlas, "find_wanted_pages"):
                wanted = self._atlas.find_wanted_pages()
                results["wanted_pages"] = wanted[:10]
        except Exception as e:
            results["wanted_error"] = str(e)

        # ── 执行钩子 ──
        for hook in self._hooks.get("on_idle", []):
            try:
                hook(results)
            except Exception as e:
                logger.warning(f"on_idle hook failed: {e}")

        return results

    def on_session_end(self, key_findings: list[str] | None = None) -> HandoffSlice:
        """
        会话结束: 经验蒸馏 + 交接协议。
        生成 HandoffSlice 供下一个 Agent/Session 消费。
        """
        elapsed = time.time() - self._session_start

        handoff = HandoffSlice(
            task_id=f"session-{int(self._session_start)}",
            current_state=f"Query count: {self._query_count}, Duration: {elapsed:.0f}s",
            key_findings=key_findings or [],
        )

        # ── 物理断点触发 (Hermes 最终持久化) ──
        self._trigger_checkpoint(handoff)

        # ── 执行钩子 ──
        for hook in self._hooks.get("on_end", []):
            try:
                hook(handoff)
            except Exception as e:
                logger.warning(f"on_end hook failed: {e}")

        if self._storage:
            self._storage.append_audit_log(
                action="session_end",
                detail=f"Duration: {elapsed:.0f}s, Queries: {self._query_count}",
            )

        return handoff

    def on_query(self, query: str) -> dict[str, Any]:
        """
        查询前的上下文注入。
        返回 MOC 导航提示和相关激活知识。
        """
        self._query_count += 1
        context: dict[str, Any] = {"query_number": self._query_count}

        # ── 执行钩子 ──
        for hook in self._hooks.get("on_query", []):
            try:
                result = hook(query, context)
                if isinstance(result, dict):
                    context.update(result)
            except Exception as e:
                logger.warning(f"on_query hook failed: {e}")

        # ── 自动断点检查 ──
        if self._query_count % self._checkpoint_threshold == 0:
            self._trigger_checkpoint()

        return context

    def _trigger_checkpoint(self, handoff: HandoffSlice | None = None) -> SessionCheckpoint:
        """
        触发物理断点 (Checkpointing)。
        将当前内存状态固化为持久化资产, 确保 Hermes 的可靠性。
        """
        self._checkpoint_counter += 1
        ckpt = SessionCheckpoint(
            session_id=f"ckpt-{int(time.time())}-{self._checkpoint_counter}",
            timestamp=time.time(),
            phase="active" if not handoff else "final",
            current_task=f"Query processing #{self._query_count}",
            context={
                "queries": self._query_count,
                "handoff": handoff.to_dict() if handoff else None
            }
        )
        
        # 将断点存入 _meta 目录
        if not self._storage:
            logger.warning("⚠️ Storage not available — skipping physical checkpoint")
            return ckpt
            
        ckpt_path = self._storage._root / "_meta" / "checkpoints"
        ckpt_path.mkdir(parents=True, exist_ok=True)
        (ckpt_path / f"{ckpt.session_id}.json").write_text(
            json.dumps(ckpt.to_dict(), indent=2), encoding="utf-8"
        )
        
        logger.info(f"💾 Checkpoint created: {ckpt.session_id} (Hermes Integrity)")
        return ckpt

    def _build_moc(self) -> dict[str, Any]:
        """
        构建 Map of Content (MOC) — 非线性导航结构。
        类似 Obsidian 的 MOC, 但自动生成。
        """
        try:
            if not self._atlas:
                return {"total_nodes": 0, "categories": {}}
            stats = self._atlas.get_stats()
            type_dist = stats.get("type_distribution", {})

            moc: dict[str, Any] = {
                "total_nodes": stats.get("node_count", 0),
                "categories": {},
            }

            for node_type, count in type_dist.items():
                moc["categories"][node_type] = count

            return moc
        except Exception:
            return {"total_nodes": 0, "categories": {}}

    def _apply_global_decay(self) -> None:
        """批量应用激活衰减。"""
        try:
            if not self._atlas or not self._atlas._conn:
                return
            self._atlas._conn.execute("""
                UPDATE nodes
                SET activation_score = MAX(0.1, activation_score * 0.95)
                WHERE updated_at < ?
            """, (time.time() - 86400,))  # 超过 24 小时的节点衰减
            self._atlas._conn.commit()
        except Exception as e:
            logger.debug(f"Global decay failed: {e}")


# ════════════════════════════════════════════
#  Wiki Doctor (Wiki 专用诊断与自愈)
# ════════════════════════════════════════════

@dataclass
class WikiDiagnosis:
    """Wiki 诊断结果。"""
    component: str
    healthy: bool
    detail: str = ""
    fix_available: bool = False
    severity: str = "info"  # info / warning / error / critical

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "healthy": self.healthy,
            "detail": self.detail,
            "fix_available": self.fix_available,
            "severity": self.severity
        }

    def __str__(self) -> str:
        icon = "✅" if self.healthy else ("🔧" if self.fix_available else "❌")
        return f"{icon} [{self.severity.upper()}] {self.component}: {self.detail}"


class WikiDoctor(WikiPlugin):
    """
    Wiki 诊断与自愈系统。

    诊断项:
    1. Index-File 一致性 (Drift)
    2. FTS5 索引健康
    3. 向量索引健康
    4. Manifest 完整性
    5. 承重边依赖链检查
    6. 孤儿页面检测
    7. 编译错误重试
    """
    name = "doctor"
    def __init__(
        self,
        atlas: AtlasIndex | None = None,
        storage: WikiStorage | None = None,
        manifest: CompilationManifest | None = None,
    ):
        self._atlas = atlas
        self._storage = storage
        self._manifest = manifest

    async def initialize(self, ctx: WikiPluginContext) -> None:
        """插件初始化入口。"""
        self._ctx = ctx
        if not self._atlas:
            self._atlas = ctx.atlas
        if not self._storage:
            self._storage = ctx.storage
        if not self._manifest:
            self._manifest = ctx.manifest
        logger.info("⚕️ Wiki Doctor plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        if hook == WikiHook.DOCTOR_DIAGNOSE:
            return self.diagnose()
        return None

    def diagnose(self) -> list[WikiDiagnosis]:
        """执行全面诊断。"""
        results: list[WikiDiagnosis] = []
        results.append(self._check_storage_structure())
        results.append(self._check_index_health())
        results.append(self._check_fts_health())
        results.append(self._check_drift())
        results.append(self._check_manifest_integrity())
        results.append(self._check_orphans())
        results.append(self._check_compilation_errors())
        results.append(self._check_advisor_availability())
        return results

    def heal(self) -> list[str]:
        """尝试修复可修复的问题。"""
        actions: list[str] = []
        results = self.diagnose()

        for diag in results:
            if not diag.healthy and diag.fix_available:
                try:
                    fixed = self._fix(diag.component)
                    if fixed:
                        actions.append(f"Fixed: {diag.component} — {fixed}")
                except Exception as e:
                    actions.append(f"Failed to fix {diag.component}: {e}")

        return actions

    def _check_storage_structure(self) -> WikiDiagnosis:
        """检查四层存储结构完整性。"""
        if not self._storage:
            return WikiDiagnosis("storage_structure", True, "Storage not available")
            
        missing: list[str] = []
        for layer_name in ["raw", "knowledge"]:
            layer_path = self._storage._root / layer_name
            if not layer_path.exists():
                missing.append(layer_name)

        meta_path = self._storage._root / "_meta"
        if not meta_path.exists():
            missing.append("_meta")

        if missing:
            return WikiDiagnosis(
                "storage_structure", False,
                f"Missing directories: {missing}",
                fix_available=True,
                severity="error",
            )
        return WikiDiagnosis("storage_structure", True, "All layers present")

    def _check_index_health(self) -> WikiDiagnosis:
        """检查 SQLite 索引健康。"""
        try:
            if not self._atlas:
                 return WikiDiagnosis("index", True, "Atlas not available")
                 
            if not self._atlas._conn:
                return WikiDiagnosis(
                    "index", False, "Atlas not connected",
                    fix_available=True, severity="error",
                )
            stats = self._atlas.get_stats()
            return WikiDiagnosis(
                "index", True,
                f"Nodes: {stats['node_count']}, Relations: {stats['relation_count']}",
            )
        except Exception as e:
            return WikiDiagnosis(
                "index", False, f"Index error: {e}",
                fix_available=True, severity="error",
            )

    def _check_fts_health(self) -> WikiDiagnosis:
        """检查 FTS5 全文索引。"""
        if not self._atlas:
            return WikiDiagnosis("fts5", False, "Atlas plugin missing", severity="error")
        try:
            if not self._atlas._conn:
                return WikiDiagnosis("fts5", False, "Atlas not connected", severity="error")
            row = self._atlas._conn.execute(
                "SELECT COUNT(*) c FROM node_fts"
            ).fetchone()
            count = row["c"] if row else 0
            return WikiDiagnosis("fts5", True, f"FTS5 entries: {count}")
        except Exception as e:
            return WikiDiagnosis(
                "fts5", False, f"FTS5 error: {e}",
                fix_available=True, severity="warning",
            )

    def _check_drift(self) -> WikiDiagnosis:
        """检查 Index-File 漂移。"""
        if not self._atlas or not self._storage:
            return WikiDiagnosis("drift", False, "Atlas or Storage plugin missing", severity="error")
        try:
            drift = self._atlas.detect_drift(self._storage._root / "knowledge")
            orphaned = len(drift.get("orphaned_in_index", []))
            missing = len(drift.get("missing_in_index", []))

            if orphaned > 0 or missing > 0:
                return WikiDiagnosis(
                    "drift", False,
                    f"Orphaned in index: {orphaned}, Missing in index: {missing}",
                    fix_available=True, severity="warning",
                )
            return WikiDiagnosis("drift", True, "No drift detected")
        except Exception as e:
            return WikiDiagnosis("drift", False, f"Drift check error: {e}", severity="warning")

    def _check_manifest_integrity(self) -> WikiDiagnosis:
        """检查 Manifest 完整性。"""
        if not self._manifest:
            return WikiDiagnosis("manifest", True, "Manifest not available")
            
        entries = self._manifest.get_all_entries()
        error_entries = [e for e in entries.values() if e.status == "error"]

        if error_entries:
            return WikiDiagnosis(
                "manifest", False,
                f"{len(error_entries)} compilation errors in manifest",
                fix_available=True, severity="warning",
            )
        return WikiDiagnosis(
            "manifest", True,
            f"Manifest OK: {len(entries)} entries",
        )

    def _check_orphans(self) -> WikiDiagnosis:
        """检查孤儿页面。"""
        try:
            if self._atlas and hasattr(self._atlas, "find_orphans"):
                orphans = self._atlas.find_orphans()
                if len(orphans) > 10:
                    return WikiDiagnosis(
                        "orphans", False,
                        f"{len(orphans)} orphan pages (no incoming links)",
                        severity="info",
                    )
                return WikiDiagnosis("orphans", True, f"Orphans: {len(orphans)}")
            return WikiDiagnosis("orphans", True, "Atlas not available")
        except Exception as e:
            return WikiDiagnosis("orphans", False, f"Orphan check error: {e}", severity="info")

    def _check_compilation_errors(self) -> WikiDiagnosis:
        """检查编译错误积压。"""
        if not self._manifest:
             return WikiDiagnosis("compilation_errors", True, "Manifest not available")
             
        entries = self._manifest.get_all_entries()
        retryable = [
            e for e in entries.values()
            if e.status == "error" and e.retry_count < 3
        ]

        if retryable:
            return WikiDiagnosis(
                "compilation_errors", False,
                f"{len(retryable)} retryable compilation errors",
                fix_available=True, severity="warning",
            )
        return WikiDiagnosis("compilation_errors", True, "No retryable errors")

    def _check_advisor_availability(self) -> WikiDiagnosis:
        """检查军师 (Advisor) 策略可用性 — 环境感知动态检测。"""
        try:
            from engine.advisor import ModelRegistry
            registry = ModelRegistry()
            resolved = registry.resolve_model_hint(hint=None, specialty="reasoning", scenario="general")
            return WikiDiagnosis(
                "advisor", True, f"Advisor strategy available: {resolved} (environment-aware)",
                severity="info"
            )
        except RuntimeError as e:
            # 没有任何可用模型
            return WikiDiagnosis(
                "advisor", False, f"No available advisor models: {e}",
                fix_available=False, severity="warning",
            )
        except Exception as e:
            return WikiDiagnosis(
                "advisor", True, f"Advisor check skipped ({type(e).__name__})",
                severity="info"
            )

    def _fix(self, component: str) -> str | None:
        """尝试修复指定组件。"""
        if component == "storage_structure":
            if not self._storage or not hasattr(self, "_ctx") or not self._ctx:
                return "Error: Storage or Context not initialized"
            # NOTE: initialize is async in storage.py, calling sync here will fail at runtime 
            # if not wrapped in a runner, but fixing signature first.
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                     asyncio.create_task(self._storage.initialize(self._ctx))
                     return "Initialization task scheduled (async)"
                else:
                     asyncio.run(self._storage.initialize(self._ctx))
                     return "Initialized (sync run)"
            except Exception as e:
                return f"Initialization failed: {e}"

        if component == "drift":
            if not self._atlas or not self._storage:
                return "Error: Atlas or Storage not initialized"
            drift = self._atlas.detect_drift(self._storage._root / "knowledge")
            orphaned = drift.get("orphaned_in_index", [])
            for path in orphaned:
                if not self._atlas or not self._atlas._conn:
                    continue
                node_data = self._atlas._conn.execute(
                    "SELECT id FROM nodes WHERE file_path = ?", (path,)
                ).fetchone()
                if node_data:
                    self._atlas.delete_node(node_data["id"])
            return f"Removed {len(orphaned)} orphaned index entries"

        if component == "compilation_errors":
            if not self._manifest:
                return "Error: Manifest not initialized"
            entries = self._manifest.get_all_entries()
            retried = 0
            for entry in entries.values():
                if entry.status == "error" and entry.retry_count < 3:
                    entry.status = "pending"  # 标记为待重编译
                    retried += 1
            self._manifest.save()
            return f"Reset {retried} entries for recompilation"

        return None
