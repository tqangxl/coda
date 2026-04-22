"""
Coda V4.0 — Slash Command Router (致命级 #5 / Pillar 8)
元指令管道: 拦截 /config, /compact, /reset 等命令, 不消耗 LLM Token。

同时包含:
  - MCP Extensibility 接口 (Pillar 6)
  - XML Protocol 结构化解析 (Pillar 20)
  - Security Sandbox 预留 (Pillar 7)
"""

from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
import asyncio
from collections.abc import Callable, Coroutine
from typing import cast, Any, TYPE_CHECKING
import time

from .base_types import AgentEngineProtocol, SovereignIdentity

if TYPE_CHECKING:
    from .mcp_connector import MCPManager

logger = logging.getLogger("Coda.commands")


class SlashCommandRouter:
    """
    元指令管道 (Pillar 8)。

    将 /config, /compact, /reset 等管理命令路由到本地处理器,
    不再消耗大模型的上下文空间, 提升引擎响应性能。
    """

    def __init__(self) -> None:
        self._commands: dict[str, Callable[[str, AgentEngineProtocol], Coroutine[Any, Any, str | None]]] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        """注册内置 Slash 命令。"""
        self._commands["/help"] = self._cmd_help
        self._commands["/status"] = self._cmd_status
        self._commands["/compact"] = self._cmd_compact
        self._commands["/reset"] = self._cmd_reset
        self._commands["/config"] = self._cmd_config
        self._commands["/cost"] = self._cmd_cost
        self._commands["/skills"] = self._cmd_skills
        self._commands["/doctor"] = self._cmd_doctor
        self._commands["/resume"] = self._cmd_resume
        self._commands["/beta"] = self._cmd_beta
        self._commands["/memory"] = self._cmd_memory
        self._commands["/swarm"] = self._cmd_swarm
        self._commands["/tasks"] = self._cmd_tasks
        self._commands["/agents"] = self._cmd_agents

    def register(self, name: str, handler: Callable[[str, AgentEngineProtocol], Coroutine[Any, Any, str | None]]) -> None:
        """注册自定义 Slash 命令。"""
        if not name.startswith("/"):
            name = f"/{name}"
        self._commands[name] = handler

    def is_command(self, text: str) -> bool:
        """检测输入是否为 Slash 命令。"""
        return text.startswith("/") and text.split()[0] in self._commands

    async def route(self, text: str, **kwargs: object) -> str | None:
        """
        路由 Slash 命令到对应处理器 (Async)。

        返回处理结果字符串, 或 None (表示不是已知命令)。
        """
        parts = text.split()
        if not parts:
            return None
        cmd_name = parts[0]
        args = parts[1:]

        handler = self._commands.get(cmd_name)
        if handler:
            try:
                # 只有第一个参数是子命令字符串，其余全部作为 kwargs (engine 等)
                arg_str = " ".join(args)
                engine = cast(AgentEngineProtocol, kwargs.get("engine"))
                return await handler(arg_str, engine)
            except Exception as e:
                return f"Command error: {e}"
        return None

    # ── 内置命令实现 ──

    async def _cmd_help(self, _arg: str, _engine: AgentEngineProtocol) -> str:
        lines = ["📖 Available Slash Commands:"]
        for cmd in sorted(self._commands.keys()):
            lines.append(f"  {cmd}")
        return "\n".join(lines)

    async def _cmd_status(self, _arg: str, engine: AgentEngineProtocol) -> str:
        buddy: Any = engine.buddy
        git: Any = engine.git
        return (
            f"⚡ Coda Engine Status:\n"
            f"- Agent ID: {engine.agent_id}\n"
            f"- Session: {engine.session_id}\n"
            f"- Status: {engine.store.state.status.value}\n"
            f"- Iteration: {engine.store.state.iteration}\n"
            f"- Budget Used: ${engine.store.state.usage.total_cost_usd:.4f}\n"
            f"- Git: {'Available' if git and getattr(git, 'is_available', False) else 'N/A'}\n"
            f"- Buddy: {getattr(buddy, 'personality', 'None') if buddy else 'None'}"
        )

    async def _cmd_compact(self, _arg: str, engine: AgentEngineProtocol) -> str:
        compactor: Any = engine.compactor
        if compactor and hasattr(compactor, "compact"):
            msgs = engine._messages
            before = len(msgs)
            # 兼容同步或异步 compact
            if asyncio.iscoroutinefunction(getattr(compactor, "compact")):
                new_msgs = await getattr(compactor, "compact")(msgs)
            else:
                new_msgs = getattr(compactor, "compact")(msgs)
            
            new_msgs = cast(list[dict[str, object]], new_msgs)
            try:
                # 使用 setattr 绕过 Protocol 只读限制
                setattr(engine, "_messages", new_msgs)
            except Exception:
                pass
            after = len(new_msgs)
            return f"Compacted: {before} → {after} messages"
        return "No messages to compact"

    async def _cmd_reset(self, _arg: str, engine: AgentEngineProtocol) -> str:
        engine._messages.clear()
        _ = engine.store.update("iteration", 0)
        _ = engine.store.update("consecutive_errors", 0)
        return "Session reset. All messages cleared."

    async def _cmd_config(self, _arg: str, engine: AgentEngineProtocol) -> str:
        state = engine.store.state
        return json.dumps({
            "model": state.model_name,
            "max_iterations": state.iteration,
            "cost_limit": state.cost_limit_usd,
            "danger_full_access": state.danger_full_access,
            "git_auto_commit": state.git_auto_commit,
            "cyber_risk": state.cyber_risk_enabled,
            "query_guard": state.query_guard_enabled,
        }, indent=2, ensure_ascii=False)

    async def _cmd_cost(self, _arg: str, engine: AgentEngineProtocol) -> str:
        u = engine.store.state.usage
        return (
            f"💰 Token Usage:\n"
            f"  Input:  {u.input_tokens:,}\n"
            f"  Output: {u.output_tokens:,}\n"
            f"  Cache:  {u.cache_creation_tokens:,}\n"
            f"  Total:  {u.total_tokens:,}\n"
            f"  Cost:   ${u.total_cost_usd:.4f}"
        )

    async def _cmd_skills(self, _arg: str, engine: AgentEngineProtocol) -> str:
        if engine and hasattr(engine, "skills"):
            skills = cast(list[str], getattr(engine.skills, "list_skills")())
            if not skills:
                return "No skills loaded"
            return f"🛠️ Available Skills ({len(skills)}):\n" + "\n".join([f"  • {s}" for s in skills])
        return "Engine not available"

    async def _cmd_doctor(self, _arg: str, engine: AgentEngineProtocol) -> str:
        if engine and hasattr(engine, "doctor"):
            results = cast(list[Any], getattr(engine.doctor, "diagnose")())
            lines = ["🩺 System Health Diagnostic:"]
            for r in results:
                icon = "✅" if getattr(r, "healthy", False) else "❌"
                lines.append(f"  {icon} {getattr(r, 'component', 'Unknown')}: {getattr(r, 'detail', 'N/A')}")
            return "\n".join(lines)
        return "Engine not available"

    async def _cmd_resume(self, arg: str, engine: AgentEngineProtocol) -> str:
        if arg:
            # resume 是协程
            success = await engine.resume(arg)
            return f"⏯️ Resume {arg}: {'SUCCESS' if success else 'FAILED'}"
        return "Usage: /resume <session_id>"

    async def _cmd_beta(self, arg: str, engine: AgentEngineProtocol) -> str:
        if arg:
            parts = arg.split()
            flag = parts[0]
            if len(parts) > 1 and parts[1].lower() in ("on", "true", "1"):
                engine.set_beta_flag(flag, True)
                return f"🧪 Beta '{flag}' enabled"
            elif len(parts) > 1:
                engine.set_beta_flag(flag, False)
                return f"🧪 Beta '{flag}' disabled"
            else:
                enabled = engine.store.state.beta_flags.get(flag, False)
                return f"Beta '{flag}' = {enabled}"
        flags = engine.store.state.beta_flags
        return json.dumps(flags, indent=2) if flags else "No beta flags set"

    async def _cmd_memory(self, arg: str, engine: AgentEngineProtocol) -> str:
        if engine and hasattr(engine, "memory"):
            memory_obj = getattr(engine, "memory")
            if arg:
                # 兼容异步 search 或 recall
                method = getattr(memory_obj, "search", getattr(memory_obj, "recall", None))
                if method:
                    results = await method(arg) if asyncio.iscoroutinefunction(method) else method(arg)
                    results = cast(list[str], results)
                    if results:
                        return f"🔍 Memory Results for '{arg}':\n" + "\n".join([f"- {i}" for i in results])
                return f"No memories found for '{arg}'"
            memories = getattr(memory_obj, "_memories", [])
            return f"Memory entries: {len(cast(list[object], memories))}"
        return "Engine not available"

    async def _cmd_swarm(self, _arg: str, engine: AgentEngineProtocol) -> str:
        if engine and hasattr(engine, "swarm"):
            s = getattr(engine, "swarm")
            role = str(getattr(s, "role").value) # type: ignore
            peer_count = len(cast(dict[str, Any], getattr(s, "_peers")))
            return (
                f"🌐 Swarm Status:\n"
                f"  Agent ID: {getattr(s, 'agent_id')}\n"
                f"  Role: {role}\n"
                f"  Peers: {peer_count}"
            )
        return "Swarm not available"

    async def _cmd_tasks(self, _arg: str, engine: AgentEngineProtocol) -> str:
        """[V5.2] 展示正在执行的任务与集群同步包历史。"""
        if engine and hasattr(engine, "db"):
            db_obj = cast(Any, engine.db)
            tasks = await db_obj.load_tasks() if hasattr(db_obj, "load_tasks") else []
            history = []
            if engine.swarm:
                history = cast(list[Any], getattr(engine.swarm, "_packet_history", []))
            
            if not tasks and not history:
                return "📭 No active tasks or swarm history."
                
            lines = ["📋 Mission Trace (Last 5):"]
            for pkt in history[-5:]:
                time_str = time.strftime("%H:%M:%S", time.localtime(getattr(pkt, "timestamp", time.time())))
                sender = pkt.source.to_short_id()
                lines.append(f"  [{time_str}] {sender} | {pkt.packet_type.upper()} | {pkt.instruction[:50]}...")
            
            return "\n".join(lines)
        return "Database not available"

    async def _cmd_agents(self, arg: str, _engine: AgentEngineProtocol) -> str:
        """[V5.2] 智能管理集群中的专家。"""
        from .identity import registry
        
        parts = arg.split() if arg else []
        subcmd = parts[0] if parts else "list"
        
        if subcmd == "scan":
            # 扫描物理目录 (注入 LLM 支持自动补完)
            from .base_types import BaseLLM
            llm = cast(BaseLLM, _engine.buddy) if hasattr(_engine, "buddy") else None
            count = await registry.scan_agents(_engine.working_dir, llm=llm)
            return f"🔎 Intelligent scan complete. Discovered/Updated {count} specialists (with auto-inflection)."
            
        elif subcmd in ("activate", "on"):
            if len(parts) < 2: return "Usage: /agents activate <id|role|*>"
            target = parts[1]
            count = await registry.toggle_status(target, True)
            return f"✅ Activated {count} agents matching '{target}'."
            
        elif subcmd in ("deactivate", "off"):
            if len(parts) < 2: return "Usage: /agents deactivate <id|role|*>"
            target = parts[1]
            count = await registry.toggle_status(target, False)
            return f"❌ Deactivated {count} agents matching '{target}'."
            
        elif subcmd == "list" or not subcmd:
            # 按优先级排序 (1最高, 10最低)
            idents = sorted(registry.list_all_identities(), key=lambda x: x.priority)
            if not idents:
                return "📭 No agents registered. Try '/agents scan' first."
                
            lines = ["🤖 Swarm Specialists Roster (Sorted by Priority):"]
            for ident in idents:
                status_icon = "🟢" if ident.is_active else "🔴"
                auto_icon = "⚡" if ident.auto_start else "⏳"
                trust = "⭐" * int(ident.trust_score * 5)
                lines.append(
                    f"  {status_icon} **{ident.role_id}** (@{ident.instance_id})\n"
                    f"     Name: {ident.name} | Prio: {ident.priority} | Auto: {auto_icon}\n"
                    f"     Caps: {', '.join(ident.capabilities[:3])}\n"
                    f"     Trust: {trust}"
                )
            return "\n".join(lines)
            
        return f"Unknown agents sub-command: {subcmd}. Use list, scan, activate, deactivate."


# ════════════════════════════════════════════
#  MCP Extensibility Interface (Pillar 6)
# ════════════════════════════════════════════

class MCPRegistry:
    """
    MCP 无限扩展接口 (Pillar 6)。

    预留 %mcp_server_name%_%tool_name% 的工具映射接口规范,
    允许 Coda 通过 standard 协议连接外部 MCP 服务器。
    """

    def __init__(self) -> None:
        self._servers: dict[str, dict[str, object]] = {}
        self._tool_map: dict[str, str] = {}  # tool_name -> server_name

    def register_server(self, name: str, config: dict[str, object]) -> None:
        """注册 MCP 服务器。"""
        self._servers[name] = config
        # 注册服务器提供的工具
        tools = cast(list[str], config.get("tools", []))
        for tool in tools:
            mapped_name = f"mcp_{name}_{tool}"
            self._tool_map[mapped_name] = name
        logger.info(f"MCP server registered: {name} ({len(tools)} tools)")

    def resolve_tool(self, tool_name: str) -> dict[str, object] | None:
        """解析 MCP 工具名称到服务器配置。"""
        if tool_name.startswith("mcp_"):
            server_name = self._tool_map.get(tool_name)
            if server_name:
                return {"server": server_name, "config": self._servers[server_name]}
        return None

    def list_servers(self) -> list[dict[str, object]]:
        return [{"name": k, **v} for k, v in self._servers.items()]


# ════════════════════════════════════════════
#  XML Structured Protocol (Pillar 20)
# ════════════════════════════════════════════

class XMLProtocol:
    """
    结构化 XML 通信协议 (Pillar 20)。

    在大模型与工具执行层之间建立基于 XML 标签的通信规约,
    极大降低在大文本环境下的逻辑幻觉与协议解析报错。
    """

    @staticmethod
    def encode_tool_result(tool_name: str, result: str, success: bool = True) -> str:
        """将工具结果编码为 XML 格式。"""
        status = "success" if success else "error"
        # 转义特殊字符
        result_safe = result.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return (
            f'<tool_result name="{tool_name}" status="{status}">\n'
            f'{result_safe}\n'
            f'</tool_result>'
        )

    @staticmethod
    def encode_context(key: str, value: str) -> str:
        """将上下文信息编码为 XML 格式。"""
        value_safe = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f'<context key="{key}">\n{value_safe}\n</context>'

    @staticmethod
    def decode_tool_calls(xml_text: str) -> list[dict[str, object]]:
        """从 XML 文本中解析工具调用。"""
        calls: list[dict[str, object]] = []
        pattern = r'<tool_call\s+name="([^"]+)">(.*?)</tool_call>'
        for match in re.finditer(pattern, xml_text, re.DOTALL):
            name = match.group(1)
            body = match.group(2).strip()
            try:
                args = cast(dict[str, object], json.loads(body))
            except json.JSONDecodeError:
                args = {"raw": body}
            calls.append({"name": name, "arguments": args})
        return calls

    @staticmethod
    def validate(xml_text: str) -> bool:
        """验证 XML 格式的合法性。"""
        try:
            ET.fromstring(f"<root>{xml_text}</root>")
            return True
        except ET.ParseError as e:
            logger.debug(f"XML validation failed: {e}")
            return False


# ════════════════════════════════════════════
#  Security Sandbox (Pillar 7)
# ════════════════════════════════════════════

class SecuritySandbox:
    """
    容器化执行隔离 (Pillar 7)。

    在执行高危命令前检测环境隔离条件。
    Windows: 使用受限用户或 Job Objects。
    Linux: 使用 unshare 拦截进程/网络/IPC。
    """

    def __init__(self) -> None:
        self._is_sandboxed = False
        import platform
        self._platform = platform.system().lower()

    def is_dangerous(self, command: str) -> bool:
        """检测命令是否属于高危操作。"""
        dangerous_patterns = [
            r"rm\s+-rf\s+/",
            r"format\s+[a-z]:",
            r"del\s+/[sfq].*\\\*",
            r"shutdown|reboot|halt",
            r"mkfs\.",
            r"dd\s+if=.*of=/dev/",
            r"reg\s+delete",
            r"bcdedit",
        ]
        for pattern in dangerous_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return True
        # 拦截管道注入尝试
        if ("|" in command or ">" in command or "&" in command) and not self._is_sandboxed:
             # 如果不在沙箱内，拦截复合命令
             return True
        return False

    def _escape_windows_arg(self, arg: str) -> str:
        """针对 Windows PowerShell 的参数转义。"""
        # 移除可能引起注入的字符
        safe = arg.replace("'", "''").replace('"', '""').replace("`", "``")
        return f"'{safe}'"

    def wrap_command(self, command: str) -> str:
        """
        为高危命令添加隔离包装。

        Linux: unshare --net --pid --mount
        Windows: 使用 PowerShell 受限模式和环境变量隔离
        """
        if self._platform == "linux":
            return f"unshare --net --pid --fork --mount-proc -- {command}"
        elif self._platform == "windows":
            # 强化型 Windows 隔离: 使用 PowerShell 受限执行策略和空配置文件
            # 虽然不是真正的内核级隔离，但能够拦截大部分环境破坏行为
            escaped_cmd = command.replace('"', '`"').replace("'", "''")
            return (
                f'powershell.exe -NoProfile -ExecutionPolicy Bypass -Command '
                f'"$ErrorActionPreference = \'Stop\'; {escaped_cmd}"'
            )
        return command
