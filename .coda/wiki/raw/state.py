"""
Coda V5.1 — Reactive App State (Pillar 31)
响应式全局状态机: 像操作系统的内核一样，全量同步 Agent 的每一个念头与状态。
"""

from __future__ import annotations

import json
import logging
import threading
import time
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import TYPE_CHECKING, cast, Any

from .base_types import AgentStatus, LoopPhase, TaskStatus, TokenUsage, ToolCall

if TYPE_CHECKING:
    pass

logger = logging.getLogger("Coda.state")


@dataclass
class AppState:
    """中央大脑状态机。"""

    # ── 身份 ──
    agent_id: str = "commander"
    session_id: str = ""
    model_name: str = field(default_factory=lambda: os.getenv("DEFAULT_MODEL_NAME", " "))

    # ── 状态 ──
    status: AgentStatus = AgentStatus.IDLE
    loop_phase: LoopPhase = LoopPhase.INIT
    iteration: int = 0
    max_iterations: int = 200
    
    # ── 认知追踪 ──
    current_intent: str = ""
    task_status: TaskStatus = TaskStatus.PENDING
    needs_user_input: bool = False
    is_paused: bool = False

    # ── Token ──
    usage: TokenUsage = field(default_factory=TokenUsage)
    cost_limit_usd: float = 5.0

    # ── 工具历史 ──
    tool_history: list[ToolCall] = field(default_factory=list)
    pending_tool_calls: int = 0

    # ── Git 快照 ──
    git_auto_commit: bool = True
    git_commits_count: int = 0
    last_git_hash: str = ""

    # ── 安全位 ──
    danger_full_access: bool = False
    cyber_risk_enabled: bool = True
    query_guard_enabled: bool = True

    # ── 上下文 ──
    working_directory: str = ""
    active_files: list[str] = field(default_factory=list)
    git_status_snapshot: str = ""
    loaded_skills: list[str] = field(default_factory=list)

    # ── 错误恢复 ──
    consecutive_errors: int = 0
    max_consecutive_errors: int = 5
    is_self_healing: bool = False
    thought: str = ""

    # ── Beta 灰度 ──
    beta_flags: dict[str, bool] = field(default_factory=dict)
    messages: list[dict[str, object]] = field(default_factory=list)

    # ── 性能 ──
    total_time_saved: float = 0.0
    benchmark_mode: bool = False

    # ── [V5.1] QA Completion Status ──
    qa_passed: bool = False
    qa_report: str = ""

    # ── 时间戳 ──
    started_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)


class AppStateStore:
    """响应式状态管理器。"""

    def __init__(self, initial_state: AppState | None = None) -> None:
        self._state = initial_state or AppState()
        self._lock = threading.RLock()
        self._subscribers: list[Callable[[AppState, str], None]] = []
        self._snapshots: list[dict[str, object]] = []

    @property
    def state(self) -> AppState:
        return self._state

    def update(self, field_name: str, value: object, *, silent: bool = False) -> None:
        with self._lock:
            if not hasattr(self._state, field_name):
                raise AttributeError(f"AppState has no field '{field_name}'")
            setattr(self._state, field_name, value)
            self._state.last_activity = time.time()
            if not silent:
                self.notify(field_name)

    def batch_update(self, updates: Mapping[str, object]) -> None:
        with self._lock:
            for k, v in updates.items():
                if hasattr(self._state, k):
                    setattr(self._state, k, v)
            self._state.last_activity = time.time()
            self.notify("batch")

    def subscribe(self, callback: Callable[[AppState, str], None]) -> None:
        self._subscribers.append(callback)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            snap = cast(dict[str, object], asdict(self._state))
            snap["status"] = self._state.status.value
            snap["loop_phase"] = self._state.loop_phase.value
            self._snapshots.append(snap)
            return snap

    def restore(self, snapshot: Mapping[str, object]) -> None:
        with self._lock:
            for k, v in snapshot.items():
                if k == "status":
                    self._state.status = AgentStatus(str(v))
                elif k == "loop_phase":
                    self._state.loop_phase = LoopPhase(str(v))
                elif k == "usage" and isinstance(v, dict):
                    typed_v = cast("dict[str, object]", v)
                    self._state.usage = TokenUsage(
                        input_tokens=int(cast(Any, typed_v.get("input_tokens", 0))),
                        output_tokens=int(cast(Any, typed_v.get("output_tokens", 0))),
                        cache_creation_tokens=int(cast(Any, typed_v.get("cache_creation_tokens", 0))),
                        cache_read_tokens=int(cast(Any, typed_v.get("cache_read_tokens", 0))),
                        total_cost_usd=float(cast(Any, typed_v.get("total_cost_usd", 0.0))),
                    )
                elif hasattr(self._state, k):
                    setattr(self._state, k, v)

    def save_to_file(self, path: Path) -> None:
        snap = self.snapshot()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snap, indent=2, default=str), encoding="utf-8")

    def load_from_file(self, path: Path) -> bool:
        if not path.exists():
            return False
        data = json.loads(path.read_text(encoding="utf-8"))
        self.restore(data)
        return True

    def record_tool_call(self, call: ToolCall) -> None:
        with self._lock:
            self._state.tool_history.append(call)
            self._state.last_activity = time.time()

    def is_over_budget(self) -> bool:
        return self._state.usage.total_cost_usd >= self._state.cost_limit_usd

    def is_over_iterations(self) -> bool:
        return self._state.iteration >= self._state.max_iterations

    def should_stop(self) -> bool:
        return (
            self.is_over_budget()
            or self.is_over_iterations()
            or self._state.status == AgentStatus.TERMINATED
            or self._state.consecutive_errors >= self._state.max_consecutive_errors
        )

    def notify(self, changed_field: str) -> None:
        for cb in self._subscribers:
            try:
                cb(self._state, changed_field)
            except Exception as e:
                logger.error(f"Subscriber {cb} failed when handling {changed_field}: {e}")
