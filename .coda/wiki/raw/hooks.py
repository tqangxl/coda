"""
Coda V4.0 — Defensive Hooks & Tool Policy (Pillar 3)
Pre/Post Tool 钩子引擎: 所有工具执行的必经通道。

组合了:
  - Pillar 3: Defensive Hooks
  - Pillar 4: Git Auto-Checkpoint (委托给 git_checkpoint.py)
  - Pillar 27: Query Guard 拦截
  - Pillar 32: CyberRisk 动态防御
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .base_types import AgentStatus, ToolCall
from .state import AppStateStore
from .git_checkpoint import GitCheckpoint

logger = logging.getLogger("Coda.hooks")


# ── CyberRisk 安全规约 (Pillar 32) ──
# 这些模式如果在命令参数中出现, 将触发拦截
CYBER_RISK_PATTERNS = [
    r"rm\s+(-rf?|--recursive).*(/|\\)",      # 大面积递归删除
    r"chmod\s+777",                            # 过度放开权限
    r"curl.*\|\s*(bash|sh)",                   # 管道执行远程脚本
    r"cat\s+.*\.env",                          # 读取环境凭证
    r"echo\s+.*>\s*/etc/",                     # 写入系统配置
    r"netstat|ss\s+-",                         # 网络侦查
    r"iptables|firewall-cmd|ufw",             # 修改防火墙
    r"wget.*-O\s*/",                           # 下载到系统目录
    r"eval\s*\(",                              # eval 注入
    r"__import__\s*\(",                        # Python 动态导入
]

# ── Query Guard 失控模式 (Pillar 27) ──
MAX_TOOL_CALLS_PER_MINUTE = 30
MAX_CONSECUTIVE_SAME_TOOL = 10


@dataclass
class HookResult:
    """钩子执行结果。"""
    allowed: bool = True
    reason: str = ""
    modified_args: dict[str, object] | None = None


class HookEngine:
    """
    防御型钩子引擎。

    所有的 Tool 执行必须通过此引擎，它负责:
    1. Pre-Tool: 安全检查 + Git 快照
    2. Post-Tool: 审计记录 + Git 存档
    3. Query Guard: 防止失控的工具调用死循环
    """

    def __init__(self, store: AppStateStore, git: GitCheckpoint):
        self._store = store
        self._git = git
        self._hooks: dict[str, list[Callable[..., Any]]] = {}
        self._recent_calls: list[float] = []  # 用于速率限制

    def pre_tool(self, tool_name: str, arguments: dict[str, object]) -> HookResult:
        """
        Pre-Tool Hook: 在工具执行前的安全关卡。

        检查顺序:
        1. CyberRisk 风险扫描
        2. Query Guard 速率检测
        3. Git 修改前快照
        """
        state = self._store.state

        # ── Step 1: CyberRisk 扫描 (Pillar 32) ──
        if state.cyber_risk_enabled and tool_name in ("run_command", "bash", "shell"):
            cmd = arguments.get("command", arguments.get("CommandLine", ""))
            risk = self._scan_cyber_risk(cmd)
            if risk:
                if not state.danger_full_access:
                    logger.warning(f"🛡️ CyberRisk BLOCKED: {risk}")
                    return HookResult(allowed=False, reason=f"CyberRisk: {risk}")
                else:
                    logger.warning(f"⚠️ CyberRisk WARNING (DangerFullAccess): {risk}")

        # ── Step 2: Query Guard 速率检测 (Pillar 27) ──
        if state.query_guard_enabled:
            guard_result = self._check_query_guard(tool_name)
            if not guard_result.allowed:
                return guard_result

        # ── Step 3: Git 修改前快照 (Pillar 4) ──
        if state.git_auto_commit and tool_name in (
            "write_to_file", "replace_file_content", "multi_replace_file_content",
            "create_file", "edit_file", "str_replace_editor",
        ):
            commit_hash = self._git.pre_tool_snapshot(tool_name)
            if commit_hash:
                self._store.batch_update({
                    "git_commits_count": state.git_commits_count + 1,
                    "last_git_hash": commit_hash,
                })

        # ── 更新状态 ──
        self._store.update("status", AgentStatus.TOOL_EXECUTING)
        self._store.update("pending_tool_calls", state.pending_tool_calls + 1)

        return HookResult(allowed=True)

    def post_tool(self, tool_name: str, call_record: ToolCall) -> None:
        """
        Post-Tool Hook: 工具执行后的审计与存档。

        执行:
        1. 记录工具执行结果
        2. Git 修改后存档 (带 Success/Fail 标记)
        3. 更新错误计数器
        """
        state = self._store.state

        # ── 记录历史 ──
        self._store.record_tool_call(call_record)

        # ── Git 修改后存档 (Pillar 4) ──
        if state.git_auto_commit and tool_name in (
            "write_to_file", "replace_file_content", "multi_replace_file_content",
            "create_file", "edit_file", "str_replace_editor",
        ):
            commit_hash = self._git.post_tool_snapshot(tool_name, success=call_record.success)
            if commit_hash:
                self._store.batch_update({
                    "git_commits_count": state.git_commits_count + 1,
                    "last_git_hash": commit_hash,
                })

        # ── 错误追踪 ──
        if call_record.success:
            self._store.update("consecutive_errors", 0, silent=True)
        else:
            self._store.update("consecutive_errors", state.consecutive_errors + 1)

        # ── 恢复状态 ──
        self._store.batch_update({
            "status": AgentStatus.THINKING,
            "pending_tool_calls": max(0, state.pending_tool_calls - 1),
        })

    def _scan_cyber_risk(self, command: str | object) -> str | None:
        """CyberRisk 动态防御: 扫描指令流中的安全风险模式。"""
        import re
        for pattern in CYBER_RISK_PATTERNS:
            if re.search(pattern, str(command), re.IGNORECASE):
                return f"Matched risk pattern: {pattern}"
        return None

    def _run_security_scan(self, file_path: str, content: str) -> HookResult:
        """
        Atomic Security Scan: 扫描代码片段中的高危模式与禁止标记。
        
        防止注入、硬编码密钥、禁用标记等高风险代码被写入。
        """
        if not content.strip():
            return HookResult(allowed=True)

        # 1. 检查禁止标记 (Coda Constitution 强制要求)
        forbidden = ["@ts-ignore", "eslint-disable", "any", "Placeholder", "Mock data"]
        # TODO: 在严格模式下拦截 TODO/FIXME，目前仅记录
        for f in forbidden:
            if f in content:
                # 给一定的模糊匹配空间，比如注释中的 @ts-ignore
                import re
                if re.search(rf"\b{re.escape(f)}\b", content):
                     return HookResult(allowed=False, reason=f"Forbidden marker found: {f}")

        # 2. 检查高危 Python 函数 (如果写入的是 .py 文件)
        if file_path.endswith(".py"):
            dangerous_calls = ["eval(", "exec(", "os.system(", "subprocess.Popen(", "importlib.import_module("]
            for call in dangerous_calls:
                if call in content:
                    logger.warning(f"🛡️ Security Scan WARNING: Dangerous Python call found: {call}")
                    # 如果是非全权限模式，拦截
                    if not self._store.state.danger_full_access:
                        return HookResult(allowed=False, reason=f"Dangerous Python call: {call}")

        # 3. 检查硬编码密钥 (简单正则)
        key_patterns = [
            r"sk-[a-zA-Z0-9]{48}", # OpenAI
            r"AIza[0-9A-Za-z-_]{35}", # Google API
            r"SURREALDB_PASS\s*=\s*['\"][^'\"]+['\"]", # SurrealDB
        ]
        import re
        for pattern in key_patterns:
            if re.search(pattern, content):
                return HookResult(allowed=False, reason="Hardcoded credentials/API keys detected.")

        return HookResult(allowed=True)

    def _check_query_guard(self, tool_name: str) -> HookResult:
        """
        Query Guard (Pillar 27): 动态监测并拦截失控的工具调用。

        规则:
        - 1 分钟内不超过 30 次工具调用
        - 同一工具连续调用不超过 10 次
        """
        now = time.time()
        self._recent_calls.append(now)
        # 清理 60 秒之前的记录
        self._recent_calls = [t for t in self._recent_calls if now - t < 60]

        if len(self._recent_calls) > MAX_TOOL_CALLS_PER_MINUTE:
            return HookResult(
                allowed=False,
                reason=f"QueryGuard: Rate limit exceeded ({len(self._recent_calls)} calls/min)"
            )

        # 检测连续同工具调用
        history = self._store.state.tool_history
        if len(history) >= MAX_CONSECUTIVE_SAME_TOOL:
            recent_tools = [h.tool_name for h in history[-MAX_CONSECUTIVE_SAME_TOOL:]]
            if all(t == tool_name for t in recent_tools):
                return HookResult(
                    allowed=False,
                    reason=f"QueryGuard: Tool '{tool_name}' called {MAX_CONSECUTIVE_SAME_TOOL} times consecutively"
                )

        return HookResult(allowed=True)
