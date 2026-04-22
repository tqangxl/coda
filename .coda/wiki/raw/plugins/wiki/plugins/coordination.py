"""
Coda Knowledge Engine V6.0 — Multi-Agent Coordination
多 Agent 协调协议 + 交接 + 心跳 + 屏障 + 记忆隔离 + 重试队列。

Blueprint Coverage:
  §7.2  任务延期预警 (Deferral Escalation)
  §12.2 交接协议 (Handoff Protocol)
  §12.3 心跳注册 (Agent Registry / Heartbeat)
  §12.4 状态屏障 (Barriers / wait-for)
  §12.5 物理内存隔离 (Memory Isolation)
  §13.3 契约驱动编排 (Contract-Based Orchestration)
  §13.4 延迟实例化 (Deferred Materialization)
  §13.5 后台知识收割 (Background Closeout)
  §14.3 失败持久化 (Failure Persistence / Retry Queue)
  §14.5 审计日志标准 (Audit Trail)
"""

from __future__ import annotations

from ..base_plugin import WikiPlugin, WikiHook, WikiPluginContext

import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("Coda.wiki.coordination")


# ════════════════════════════════════════════
#  §12.2 交接协议 (Handoff Protocol)
# ════════════════════════════════════════════

@dataclass
class HandoffPacket:
    """
    Context Slice (Tracecraft): 上一个 Task 完成时生成的交接包。
    """
    task_id: str
    agent_id: str
    completed_items: list[str] = field(default_factory=list)
    current_state: str = ""
    next_steps: list[str] = field(default_factory=list)
    key_findings: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "completed_items": self.completed_items,
            "current_state": self.current_state,
            "next_steps": self.next_steps,
            "key_findings": self.key_findings,
            "modified_files": self.modified_files,
            "open_questions": self.open_questions,
            "created_at": self.created_at,
        }


class HandoffManager(WikiPlugin):
    """交接协议管理器。"""
    name = "handoff"

    def __init__(self, coordination_dir: str | Path | None = None):
        self._dir = Path(coordination_dir) / "handoffs" if coordination_dir else None

    async def initialize(self, ctx: WikiPluginContext) -> None:
        if not self._dir:
            self._dir = Path(ctx.storage.coordination_dir) / "handoffs"
        self._dir.mkdir(parents=True, exist_ok=True)
        logger.info("📦 Handoff Manager plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        return None

    def create_handoff(self, packet: HandoffPacket) -> Path:
        """创建交接包。"""
        filename = f"handoff_{packet.task_id}_{int(time.time())}.json"
        path = self._dir / filename
        path.write_text(
            json.dumps(packet.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        logger.info(f"📦 Handoff created: {filename}")
        return path

    def consume_latest(self, agent_id: str | None = None) -> HandoffPacket | None:
        """消费最新的交接包。"""
        handoff_files = sorted(self._dir.glob("handoff_*.json"), reverse=True)

        for f in handoff_files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if agent_id and data.get("agent_id") == agent_id:
                    continue  # 跳过自己创建的
                return HandoffPacket(**data)
            except Exception:
                continue

        return None

    def list_handoffs(self, limit: int = 10) -> list[dict[str, Any]]:
        """列出最近的交接包。"""
        results = []
        for f in sorted(self._dir.glob("handoff_*.json"), reverse=True)[:limit]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                data["_file"] = str(f)
                results.append(data)
            except Exception:
                continue
        return results


# ════════════════════════════════════════════
#  §12.3 心跳注册 (Agent Registry)
# ════════════════════════════════════════════

@dataclass
class AgentHeartbeat:
    """Agent 心跳状态。"""
    agent_id: str
    status: str  # "active" | "idle" | "offline"
    role: str = ""
    current_task: str = ""
    last_seen: float = field(default_factory=time.time)
    capabilities: list[str] = field(default_factory=list)
    session_id: str = ""


class AgentRegistry(WikiPlugin):
    """
    Agent 心跳注册表。
    """
    name = "agent_registry"

    def __init__(self, coordination_dir: str | Path | None = None, heartbeat_ttl: float = 300):
        self._coordination_dir = coordination_dir
        self._dir = Path(coordination_dir) / "agents" if coordination_dir else None
        self._ttl = heartbeat_ttl

    async def initialize(self, ctx: WikiPluginContext) -> None:
        if not self._dir:
            self._dir = Path(ctx.storage.coordination_dir) / "agents"
        self._dir.mkdir(parents=True, exist_ok=True)
        logger.info("📇 Agent Registry plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        if hook == WikiHook.HEARTBEAT and isinstance(payload, str):
            self.heartbeat(payload)
        return None

    def register(self, heartbeat: AgentHeartbeat) -> None:
        """注册/更新 Agent 心跳。"""
        path = self._dir / f"{heartbeat.agent_id}.json"
        heartbeat.last_seen = time.time()
        path.write_text(
            json.dumps({
                "agent_id": heartbeat.agent_id,
                "status": heartbeat.status,
                "role": heartbeat.role,
                "current_task": heartbeat.current_task,
                "last_seen": heartbeat.last_seen,
                "capabilities": heartbeat.capabilities,
                "session_id": heartbeat.session_id,
            }, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def heartbeat(self, agent_id: str) -> None:
        """更新 Agent 的 last_seen 时间戳。"""
        path = self._dir / f"{agent_id}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data["last_seen"] = time.time()
                data["status"] = "active"
                path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            except Exception:
                pass

    def get_status(self, agent_id: str) -> AgentHeartbeat | None:
        """获取 Agent 状态。"""
        path = self._dir / f"{agent_id}.json"
        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            heartbeat = AgentHeartbeat(**data)

            # 判断是否超时
            if time.time() - heartbeat.last_seen > self._ttl:
                heartbeat.status = "offline"

            return heartbeat
        except Exception:
            return None

    def list_online(self) -> list[AgentHeartbeat]:
        """列出在线 Agent。"""
        online = []
        for f in self._dir.glob("*.json"):
            hb = self.get_status(f.stem)
            if hb and hb.status != "offline":
                online.append(hb)
        return online

    def unregister(self, agent_id: str) -> None:
        """注销 Agent。"""
        path = self._dir / f"{agent_id}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data["status"] = "offline"
                data["last_seen"] = time.time()
                path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            except Exception:
                pass


# ════════════════════════════════════════════
#  §12.4 状态屏障 (Barriers)
# ════════════════════════════════════════════

class TaskBarrier(WikiPlugin):
    """
    状态屏障 (wait-for 指令)。
    """
    name = "barrier"

    def __init__(self, coordination_dir: str | Path | None = None):
        self._dir = Path(coordination_dir) / "barriers" if coordination_dir else None

    async def initialize(self, ctx: WikiPluginContext) -> None:
        if not self._dir:
            self._dir = Path(ctx.storage.coordination_dir) / "barriers"
        self._dir.mkdir(parents=True, exist_ok=True)
        logger.info("🚦 Task Barrier plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        return None

    def signal_complete(self, task_id: str, result: dict[str, Any] | None = None) -> None:
        """发出任务完成信号。"""
        path = self._dir / f"{task_id}.done"
        data = {
            "task_id": task_id,
            "completed_at": time.time(),
            "result": result or {},
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.info(f"🚦 Barrier signal: {task_id} completed")

    def is_complete(self, task_id: str) -> bool:
        """检查任务是否已完成。"""
        return (self._dir / f"{task_id}.done").exists()

    def wait_for(
        self, task_id: str, timeout: float = 60, poll_interval: float = 2
    ) -> dict[str, Any] | None:
        """等待任务完成 (同步轮询)。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            path = self._dir / f"{task_id}.done"
            if path.exists():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    return {"task_id": task_id, "completed_at": time.time()}
            time.sleep(poll_interval)
        return None  # 超时

    def clear(self, task_id: str) -> None:
        """清除信号。"""
        path = self._dir / f"{task_id}.done"
        if path.exists():
            path.unlink()


# ════════════════════════════════════════════
#  §12.5 物理内存隔离
# ════════════════════════════════════════════

class MemoryIsolation(WikiPlugin):
    """
    物理内存隔离 (Prefix Isolation)。
    """
    name = "memory_isolation"

    def __init__(self, memory_root: str | Path | None = None):
        self._root = Path(memory_root) if memory_root else None

    async def initialize(self, ctx: WikiPluginContext) -> None:
        if not self._root:
            self._root = Path(ctx.storage.coordination_dir) / "memory"
        self._root.mkdir(parents=True, exist_ok=True)
        (self._root / "shared").mkdir(exist_ok=True)
        logger.info("🔒 Memory Isolation plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        return None

    def get_private_dir(self, agent_id: str) -> Path:
        """获取 Agent 的私有内存目录。"""
        d = self._root / agent_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get_shared_dir(self) -> Path:
        """获取共享内存目录。"""
        return self._root / "shared"

    def write_private(self, agent_id: str, key: str, data: Any) -> Path:
        """写入私有内存。"""
        path = self.get_private_dir(agent_id) / f"{key}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def read_private(self, agent_id: str, key: str) -> Any | None:
        """读取私有内存。"""
        path = self.get_private_dir(agent_id) / f"{key}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def write_shared(self, key: str, data: Any) -> Path:
        """写入共享内存。"""
        path = self.get_shared_dir() / f"{key}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def read_shared(self, key: str) -> Any | None:
        """读取共享内存。"""
        path = self.get_shared_dir() / f"{key}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def validate_access(self, agent_id: str, target_path: Path) -> bool:
        """验证访问权限 (只能写自己的目录或 shared)。"""
        resolved = target_path.resolve()
        private = self.get_private_dir(agent_id).resolve()
        shared = self.get_shared_dir().resolve()
        return str(resolved).startswith(str(private)) or str(resolved).startswith(str(shared))


# ════════════════════════════════════════════
#  §7.2 任务延期预警 (Deferral Escalation)
# ════════════════════════════════════════════

class DeferralEscalation(str, Enum):
    """延期严重度。"""
    NONE = "none"           # < 7 天
    SOFT_REMIND = "soft"    # 7-13 天
    TARGETED_ASK = "ask"    # 14-20 天
    FORCE_DECIDE = "force"  # 21+ 天


@dataclass
class DeferredTask:
    """延期任务。"""
    task_id: str
    title: str
    since_date: str  # YYYY-MM-DD
    days_deferred: int
    escalation: DeferralEscalation
    suggestion: str


class DeferralMonitor(WikiPlugin):
    """
    任务延期预警监控器。
    """
    name = "deferral_monitor"

    async def initialize(self, ctx: WikiPluginContext) -> None:
        self._wiki_dir = Path(ctx.wiki_dir)
        logger.info("⏰ Deferral Monitor plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        return None

    import re as _re

    SINCE_PATTERN = _re.compile(r'<!--\s*since:\s*(\d{4}-\d{2}-\d{2})\s*-->')

    def scan_file(self, file_path: Path) -> list[DeferredTask]:
        """扫描文件中的延期标记。"""
        if not file_path.exists():
            return []

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return []

        tasks = []
        lines = content.split('\n')

        for i, line in enumerate(lines):
            match = self.SINCE_PATTERN.search(line)
            if match:
                since_str = match.group(1)
                try:
                    from datetime import datetime
                    since = datetime.strptime(since_str, "%Y-%m-%d")
                    now = datetime.now()
                    days = (now - since).days

                    # 确定严重度等级
                    if days >= 21:
                        level = DeferralEscalation.FORCE_DECIDE
                        suggestion = f"FORCE DECISION: Remove / Park / Schedule. Deferred {days} days."
                    elif days >= 14:
                        level = DeferralEscalation.TARGETED_ASK
                        suggestion = f"Targeted inquiry: why is this still pending after {days} days?"
                    elif days >= 7:
                        level = DeferralEscalation.SOFT_REMIND
                        suggestion = f"Soft reminder: {days} days since last activity."
                    else:
                        level = DeferralEscalation.NONE
                        suggestion = "Within normal timeframe."

                    # 提取任务标题 (查找最近的标题行)
                    title = file_path.stem
                    for j in range(i, max(0, i - 5), -1):
                        if lines[j].strip().startswith('#'):
                            title = lines[j].strip().lstrip('#').strip()
                            break

                    if level != DeferralEscalation.NONE:
                        tasks.append(DeferredTask(
                            task_id=f"{file_path.stem}:{i+1}",
                            title=title,
                            since_date=since_str,
                            days_deferred=days,
                            escalation=level,
                            suggestion=suggestion,
                        ))
                except Exception:
                    continue

        return tasks

    def scan_directory(self, wiki_dir: Path) -> list[DeferredTask]:
        """扫描整个 Wiki 目录。"""
        all_tasks = []
        for md_file in wiki_dir.rglob("*.md"):
            all_tasks.extend(self.scan_file(md_file))
        return sorted(all_tasks, key=lambda t: t.days_deferred, reverse=True)


# ════════════════════════════════════════════
#  §14.3 失败持久化 (Retry Queue)
# ════════════════════════════════════════════

@dataclass
class RetryEntry:
    """重试队列条目。"""
    id: str
    action: str
    target: str
    payload: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    retry_count: int = 0
    max_retries: int = 3
    created_at: float = field(default_factory=time.time)
    next_retry_at: float = 0

    def should_retry(self) -> bool:
        return self.retry_count < self.max_retries and time.time() >= self.next_retry_at

    def schedule_retry(self) -> None:
        """指数退避调度。"""
        self.retry_count += 1
        delay = min(30 * (2 ** self.retry_count), 600)  # 最大 10 分钟
        self.next_retry_at = time.time() + delay


class RetryQueue(WikiPlugin):
    """
    失败持久化重试队列。
    """
    name = "retry_queue"

    def __init__(self, queue_dir: str | Path | None = None):
        self._dir = Path(queue_dir) / "pending_retries" if queue_dir else None

    async def initialize(self, ctx: WikiPluginContext) -> None:
        if not self._dir:
            self._dir = Path(ctx.storage.coordination_dir) / "pending_retries"
        self._dir.mkdir(parents=True, exist_ok=True)
        logger.info("🔄 Retry Queue plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        if hook == WikiHook.RETRY_CHECK:
            return self.get_ready_entries()
        return None

    def enqueue(self, entry: RetryEntry) -> Path:
        """入队。"""
        path = self._dir / f"{entry.id}.json"
        path.write_text(
            json.dumps({
                "id": entry.id,
                "action": entry.action,
                "target": entry.target,
                "payload": entry.payload,
                "error": entry.error,
                "retry_count": entry.retry_count,
                "max_retries": entry.max_retries,
                "created_at": entry.created_at,
                "next_retry_at": entry.next_retry_at,
            }, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        logger.info(f"📥 Retry queue: enqueued {entry.id} (attempt {entry.retry_count}/{entry.max_retries})")
        return path

    def get_ready_entries(self) -> list[RetryEntry]:
        """获取准备好重试的条目。"""
        ready = []
        for f in self._dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                entry = RetryEntry(**data)
                if entry.should_retry():
                    ready.append(entry)
            except Exception:
                continue
        return sorted(ready, key=lambda e: e.next_retry_at)

    def mark_success(self, entry_id: str) -> None:
        """标记成功 (移除)。"""
        path = self._dir / f"{entry_id}.json"
        if path.exists():
            dest = self._dir.parent / "completed" / f"{entry_id}.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            path.rename(dest)
            logger.info(f"✅ Retry success: {entry_id}")

    def mark_failed(self, entry: RetryEntry, error: str) -> None:
        """标记失败并重新调度。"""
        entry.error = error
        entry.schedule_retry()
        if entry.should_retry():
            self.enqueue(entry)
        else:
            # 永久失败 — 移到 dead-letter
            path = self._dir / f"{entry.id}.json"
            if path.exists():
                dest = self._dir.parent / "dead_letter" / f"{entry.id}.json"
                dest.parent.mkdir(parents=True, exist_ok=True)
                path.rename(dest)
                logger.error(f"💀 Dead letter: {entry.id} after {entry.retry_count} attempts")

    def get_stats(self) -> dict[str, int]:
        """获取队列统计。"""
        pending = len(list(self._dir.glob("*.json")))
        completed = len(list((self._dir.parent / "completed").glob("*.json"))) if (self._dir.parent / "completed").exists() else 0
        dead = len(list((self._dir.parent / "dead_letter").glob("*.json"))) if (self._dir.parent / "dead_letter").exists() else 0
        return {"pending": pending, "completed": completed, "dead_letter": dead}


# ════════════════════════════════════════════
#  §14.5 审计日志标准
# ════════════════════════════════════════════

class AuditTrail(WikiPlugin):
    """
    审计日志标准 (基于动词的日志)。
    """
    name = "audit"

    def __init__(self, log_path: str | Path | None = None):
        self._path = Path(log_path) if log_path else None

    async def initialize(self, ctx: WikiPluginContext) -> None:
        if not self._path:
            self._path = Path(ctx.storage.coordination_dir) / "audit.md"
        self._path.parent.mkdir(parents=True, exist_ok=True)

        if not self._path.exists():
            self._path.write_text(
                "# Coda Knowledge Engine — Audit Trail\n\n",
                encoding="utf-8"
            )
        logger.info("📜 Audit Trail plugin initialized")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        return None

    def log(
        self,
        action: str,
        target: str = "",
        detail: str = "",
        agent_id: str = "",
        task_id: str = "",
        conversation_id: str = "",
    ) -> None:
        """写入审计日志条目。"""
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        parts = [f"## [{ts}] {action}"]
        if agent_id:
            parts.append(f"- Agent: `{agent_id}`")
        if task_id:
            parts.append(f"- Task: `{task_id}`")
        if conversation_id:
            parts.append(f"- Conversation: `{conversation_id}`")
        if target:
            parts.append(f"- Target: `{target}`")
        if detail:
            parts.append(f"- Detail: {detail}")
        parts.append("")

        entry = "\n".join(parts) + "\n"

        with open(self._path, "a", encoding="utf-8") as f:
            f.write(entry)

    def get_recent(self, limit: int = 20) -> list[str]:
        """获取最近的审计日志条目。"""
        if not self._path.exists():
            return []

        content = self._path.read_text(encoding="utf-8")
        entries = content.split("\n## [")
        entries = [f"## [{e}" for e in entries[1:]]  # 跳过 header
        return entries[-limit:]


# ════════════════════════════════════════════
#  §13.3 契约驱动编排
# ════════════════════════════════════════════

@dataclass
class EngineContract:
    """
    引擎契约 (OpenArche)。
    规定输入/输出类型 + 显式声明可能产生的副作用。
    """
    engine_name: str
    input_types: list[str] = field(default_factory=list)
    output_types: list[str] = field(default_factory=list)
    side_effects: list[str] = field(default_factory=list)  # "file_write" | "index_update" | "network"
    prerequisites: list[str] = field(default_factory=list)
    idempotent: bool = False


# 预定义的引擎契约
WIKI_CONTRACTS: dict[str, EngineContract] = {
    "compiler": EngineContract(
        engine_name="MemoryCompiler",
        input_types=["markdown_files"],
        output_types=["knowledge_nodes", "relations"],
        side_effects=["file_write", "index_update"],
        prerequisites=["storage_initialized", "atlas_connected"],
    ),
    "search": EngineContract(
        engine_name="WikiSearchEngine",
        input_types=["query_text", "embedding_vector"],
        output_types=["search_results"],
        side_effects=[],
        prerequisites=["atlas_connected"],
        idempotent=True,
    ),
    "pii_sentinel": EngineContract(
        engine_name="PIISentinel",
        input_types=["text"],
        output_types=["sanitization_result"],
        side_effects=[],
        prerequisites=[],
        idempotent=True,
    ),
    "shadow_mirror": EngineContract(
        engine_name="ShadowMirror",
        input_types=["binary_files"],
        output_types=["markdown_shadows"],
        side_effects=["file_write"],
        prerequisites=["storage_initialized"],
    ),
    "enricher": EngineContract(
        engine_name="ConflictDetector",
        input_types=["knowledge_graph"],
        output_types=["conflict_reports", "gap_analysis"],
        side_effects=[],
        prerequisites=["atlas_connected"],
        idempotent=True,
    ),
}
