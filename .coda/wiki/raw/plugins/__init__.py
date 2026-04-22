"""
Coda V5.2 — Plugin System & Sidecar Manager (Phase 5)
支持异构插件同步、Node.js/TS 侧边进程管理与 UMDCS 协议转发。
"""

from __future__ import annotations
import asyncio
import json
import logging
from typing import Protocol, runtime_checkable, override, cast
from ..base_types import UniversalCognitivePacket

logger = logging.getLogger("Coda.plugins")

@runtime_checkable
class Plugin(Protocol):
    """插件基础接口。"""
    name: str
    async def initialize(self) -> None: ...
    async def shutdown(self) -> None: ...
    async def on_packet(self, packet: UniversalCognitivePacket) -> UniversalCognitivePacket | None: ...
    async def health_check(self) -> bool: ... # [V5.2] 新增健康检查钩子

class PluginRegistry:
    """插件注册表。"""
    def __init__(self):
        self._plugins: dict[str, Plugin] = {}
        # ── [V5.2] 企业级资源守卫开关 ──
        self.strict_resource_limit: bool = False # 默认仅预警

    def register(self, plugin: Plugin) -> None:
        self._plugins[plugin.name] = plugin
        logger.info(f"🔌 Plugin registered: {plugin.name}")

    async def broadcast_to_plugins(self, packet: UniversalCognitivePacket) -> list[UniversalCognitivePacket]:
        """将数据包分发给所有插件处理，并收集返回的新数据包。"""
        results = []
        for plugin in self._plugins.values():
            try:
                res = await plugin.on_packet(packet)
                if res:
                    results.append(res)
            except Exception as e:
                logger.error(f"Plugin {plugin.name} failed to process packet: {e}")
        return results

class SidecarPlugin(Plugin):
    """
    异构侧边进程插件 (Pillar: Polyglot Swarm).
    支持 TS, Go, Rust 等通过 Stdin/Stdout 或 Socket 通信。
    """
    def __init__(self, name: str, command: list[str], cwd: str = "."):
        self.name: str = name
        self.command: list[str] = command
        self.cwd: str = cwd
        self.process: asyncio.subprocess.Process | None = None

    @override
    async def initialize(self) -> None:
        """启动侧边进程。"""
        logger.info(f"🚀 Starting Sidecar Plugin: {self.name} -> {self.command}")
        self.process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.cwd
        )
        # 启动异步读取循环
        asyncio.create_task(self._read_stderr())

    async def _read_stderr(self) -> None:
        if not self.process or not self.process.stderr: return
        while True:
            line = await self.process.stderr.readline()
            if not line: break
            logger.debug(f"[Sidecar:{self.name}] {line.decode().strip()}")

    @override
    async def on_packet(self, packet: UniversalCognitivePacket, timeout: float = 10.0) -> UniversalCognitivePacket | None:
        """将 UMDCS 包转发给侧边进程，并等待响应。"""
        if not self.process or not self.process.stdin or not self.process.stdout:
            # [V5.2] 自愈：尝试自动重启启动失败的进程
            logger.warning(f"🔄 Sidecar {self.name} is down. Attempting auto-restart...")
            await self.initialize()
            if not self.process or not self.process.stdin: return None
        
        try:
            # 协议转发
            data = json.dumps(packet.to_dict()) + "\n"
            self.process.stdin.write(data.encode())
            await self.process.stdin.drain()
            
            # 等待侧边逻辑返回 (带超时保护)
            try:
                if not self.process.stdout: return None
                response_line = await asyncio.wait_for(self.process.stdout.readline(), timeout=timeout)
                if response_line:
                    res_dict = cast(dict[str, object], json.loads(response_line.decode()))
                    return UniversalCognitivePacket.from_dict(res_dict)
            except asyncio.TimeoutError:
                logger.error(f"⌛ Sidecar {self.name} timed out after {timeout}s")
                # 记录超时，触发后续健康检查失败
        except Exception as e:
            logger.error(f"Sidecar {self.name} communication error: {e}")
        
        return None

    @override
    async def health_check(self) -> bool:
        """[V5.2] 物理健康检查：检查进程是否依然存活。"""
        if self.process and self.process.returncode is None:
            return True
        return False

    @override
    async def shutdown(self) -> None:
        if self.process:
            self.process.terminate()
            await self.process.wait()
            logger.info(f"🛑 Sidecar Plugin {self.name} stopped.")

# 全局插件中心
registry = PluginRegistry()
