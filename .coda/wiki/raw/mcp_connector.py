"""
Coda V4.0 — MCP Connector (高重要度 #6)
真正的 MCP 服务器连接器: 通过 stdio 传输层连接外部 MCP 服务。

设计参考: Model Context Protocol specification
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
from typing import Any

logger = logging.getLogger("Coda.mcp")


class MCPConnection:
    """
    MCP 服务器连接 (stdio 传输)。

    通过启动子进程并通过 stdin/stdout 通信来连接 MCP 服务。
    """

    def __init__(self, name: str, command: list[str], env: dict[str, str] | None = None) -> None:
        self.name = name
        self.command = command
        self.env = env or {}
        self._process: subprocess.Popen[bytes] | None = None
        self._request_id = 0
        self._capabilities: dict[str, Any] = {}
        self._tools: list[dict[str, Any]] = []

    async def connect(self) -> bool:
        """启动 MCP 服务器进程并初始化连接。"""
        try:
            import os
            full_env = {**os.environ, **self.env}
            self._process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=full_env,
            )

            # 发送 initialize 请求
            init_result = await self._request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "Coda", "version": "4.0.0"},
            })

            if init_result:
                self._capabilities = init_result.get("capabilities", {})
                # 发送 initialized 通知
                await self._notify("notifications/initialized", {})

                # 获取可用工具列表
                tools_result = await self._request("tools/list", {})
                if tools_result:
                    self._tools = tools_result.get("tools", [])

                logger.info(f"MCP connected: {self.name} ({len(self._tools)} tools)")
                return True

            return False
        except Exception as e:
            logger.error(f"MCP connection failed for {self.name}: {e}")
            return False

    async def disconnect(self) -> None:
        """断开 MCP 连接。"""
        if self._process:
            self._process.terminate()
            self._process = None
            logger.info(f"MCP disconnected: {self.name}")

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str | None:
        """调用 MCP 工具。"""
        result = await self._request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })

        if result and "content" in result:
            parts = []
            for item in result["content"]:
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
            return "\n".join(parts)
        return None

    async def list_tools(self) -> list[dict[str, Any]]:
        """获取此 MCP 服务器提供的所有工具。"""
        return self._tools

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """发送 JSON-RPC 请求。"""
        if not self._process or not self._process.stdin or not self._process.stdout:
            return None

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }

        try:
            data = json.dumps(request)
            header = f"Content-Length: {len(data)}\r\n\r\n"
            self._process.stdin.write(header.encode() + data.encode())
            self._process.stdin.flush()

            # 读取响应
            response = await asyncio.to_thread(self._read_response)
            if response:
                return response.get("result")
            return None
        except Exception as e:
            logger.error(f"MCP request error ({method}): {e}")
            return None

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        """发送 JSON-RPC 通知 (无需响应)。"""
        if not self._process or not self._process.stdin:
            return

        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        try:
            data = json.dumps(notification)
            header = f"Content-Length: {len(data)}\r\n\r\n"
            self._process.stdin.write(header.encode() + data.encode())
            self._process.stdin.flush()
        except Exception as e:
            logger.warning(f"MCP notify error ({method}): {e}")

    def _read_response(self) -> dict[str, Any] | None:
        """同步读取 JSON-RPC 响应。"""
        if not self._process or not self._process.stdout:
            return None

        try:
            # 读取 header
            header_line = b""
            while True:
                byte = self._process.stdout.read(1)
                if not byte:
                    return None
                header_line += byte
                if header_line.endswith(b"\r\n\r\n"):
                    break

            # 提取 Content-Length
            header_str = header_line.decode("utf-8")
            length = 0
            for line in header_str.split("\r\n"):
                if line.startswith("Content-Length:"):
                    length = int(line.split(":")[1].strip())

            if length > 0:
                body = self._process.stdout.read(length)
                return json.loads(body.decode("utf-8"))
        except Exception as e:
            logger.warning(f"MCP read response error: {e}")
        return None

    @property
    def is_connected(self) -> bool:
        return self._process is not None and self._process.poll() is None


class MCPManager:
    """
    MCP 连接管理器。

    管理多个 MCP 服务器连接, 提供统一的工具注册和调用接口。
    """

    def __init__(self) -> None:
        self._connections: dict[str, MCPConnection] = {}

    async def add_server(self, name: str, command: list[str], env: dict[str, str] | None = None) -> bool:
        """添加并连接一个 MCP 服务器。"""
        conn = MCPConnection(name, command, env)
        if await conn.connect():
            self._connections[name] = conn
            return True
        return False

    async def remove_server(self, name: str) -> None:
        """断开并移除一个 MCP 服务器。"""
        conn = self._connections.pop(name, None)
        if conn:
            await conn.disconnect()

    async def call(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> str | None:
        """调用指定服务器的工具。"""
        conn = self._connections.get(server_name)
        if conn and conn.is_connected:
            return await conn.call_tool(tool_name, arguments)
        return None

    def get_all_tools(self) -> dict[str, list[dict[str, Any]]]:
        """获取所有服务器的工具列表。"""
        result: dict[str, list[dict[str, Any]]] = {}
        for name, conn in self._connections.items():
            result[name] = conn._tools
        return result

    async def shutdown(self) -> None:
        """关闭所有连接。"""
        for conn in self._connections.values():
            await conn.disconnect()
        self._connections.clear()
