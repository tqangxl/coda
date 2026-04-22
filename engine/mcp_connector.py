"""
Coda Engine V7.0 — MCP Connector

Establishing a robust cross-process communication channel via stdio
to connect external MCP servers (e.g. M-flow Cognitive Knowledge Graph).

Key Features:
- JSON-RPC 2.0 over stdio (newline delimited)
- Capability discovery
- Tool dynamic registration
- Error handling and logging
"""

import asyncio
import json
import logging
import subprocess
import os
from typing import Any, Optional

logger = logging.getLogger("Coda.mcp")

class MCPConnection:
    """
    Connects to an MCP service by starting a child process and communicating via stdin/stdout.
    Follows the standard MCP stdio protocol (newline-delimited JSON).
    """

    def __init__(self, name: str, command: list[str], env: dict[str, str] | None = None, cwd: str | None = None) -> None:
        self.name = name
        self.command = command
        self.env = env or {}
        self.cwd = cwd
        self._process: subprocess.Popen[bytes] | None = None
        self._request_id = 0
        self._capabilities: dict[str, Any] = {}
        self._tools: list[dict[str, Any]] = []
        self._initialized = False

    async def connect(self) -> bool:
        """Starts the process and performs initialization handshake."""
        try:
            full_env = os.environ.copy()
            full_env.update(self.env)

            logger.info(f"Connecting to MCP server '{self.name}' using command: {self.command}")
            self._process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=full_env,
                cwd=self.cwd,
            )

            # 启动 stderr 读取线程，防止管道阻塞
            asyncio.create_task(self._read_stderr())

            # Wait a bit for startup
            await asyncio.sleep(1)
            if self._process.poll() is not None:
                _, stderr = self._process.communicate()
                logger.error(f"MCP process '{self.name}' died immediately: {stderr.decode('utf-8', errors='replace')}")
                return False

            # 1. Initialize
            try:
                init_result = await asyncio.wait_for(
                    self._request("initialize", {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "CodaEngine", "version": "7.0"},
                    }),
                    timeout=60.0
                )
            except asyncio.TimeoutError:
                logger.error(f"MCP server '{self.name}' initialization timed out.")
                self.disconnect()
                return False

            if not init_result:
                logger.error(f"MCP server '{self.name}' failed to respond to initialize.")
                return False

            self._capabilities = init_result.get("capabilities", {})
            self._initialized = True

            # 2. Notify initialized
            await self._notify("notifications/initialized", {})

            # 3. List tools
            tools_result = await self._request("tools/list", {})
            if tools_result and "tools" in tools_result:
                self._tools = tools_result["tools"]
                logger.info(f"MCP server '{self.name}' connected. Registered {len(self._tools)} tools.")
            
            return True

        except Exception as e:
            logger.error(f"Failed to connect to MCP server '{self.name}': {e}")
            self.disconnect()
            return False

    def disconnect(self) -> None:
        """Closes the connection and terminates the process."""
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=2)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
        self._initialized = False

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str | Optional[dict[str, Any]]:
        """Invokes an MCP tool."""
        result = await self._request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })

        if not result:
            return None
            
        # Standard MCP tool response shape
        if "content" in result:
            parts = []
            for item in result["content"]:
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
            return "\n".join(parts)
            
        return result

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """Sends a JSON-RPC request and waits for response (newline delimited)."""
        if not self._process or not self._process.stdin:
            return None
        
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        
        try:
            line = json.dumps(request) + "\n"
            logger.debug(f"MCP -> [{self.name}]: {line.strip()}")
            self._process.stdin.write(line.encode("utf-8"))
            self._process.stdin.flush()

            # Read response (one line)
            return await self._read_response()
        except Exception as e:
            logger.error(f"MCP request error ({method}): {e}")
            return None

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        """Sends a JSON-RPC notification (no response)."""
        if not self._process or not self._process.stdin:
            return
        
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        
        try:
            line = json.dumps(notification) + "\n"
            self._process.stdin.write(line.encode("utf-8"))
            self._process.stdin.flush()
        except Exception as e:
            logger.warning(f"MCP notify error ({method}): {e}")

    async def _read_stderr(self) -> None:
        """从 stderr 读取日志并转发到系统日志，防止管道阻塞。"""
        if not self._process or not self._process.stderr:
            return
            
        while True:
            line_bytes = await asyncio.to_thread(self._process.stderr.readline)
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="replace").strip()
            if line:
                logger.debug(f"MCP [stderr] [{self.name}]: {line}")

    async def _read_response(self) -> dict[str, Any] | None:
        """Reads a JSON-RPC response from stdout (skipping empty lines)."""
        if not self._process or not self._process.stdout:
            return None
            
        while True:
            # We use a thread to read because stdout.readline is blocking
            line_bytes = await asyncio.to_thread(self._process.stdout.readline)
            if not line_bytes:
                return None
            
            line = line_bytes.decode("utf-8").strip()
            if not line:
                continue
                
            logger.debug(f"MCP <- [{self.name}]: {line}")
            try:
                response = json.loads(line)
                # Check if it matches our request ID if it's a response
                # (A real implementation would handle async notifications from server here)
                if response.get("id") == self._request_id:
                    return response.get("result")
                # If it's an error response
                if "error" in response and response.get("id") == self._request_id:
                    err = response["error"]
                    logger.error(f"MCP Error [{err.get('code')}]: {err.get('message')}")
                    return None
            except json.JSONDecodeError:
                # If it's not JSON, might be some stray log message?
                # Actually, standard MCP says only JSON on stdout.
                logger.debug(f"MCP non-JSON output: {line}")
                continue

class MCPManager:
    """Manages multiple MCP server connections."""

    def __init__(self) -> None:
        self._connections: dict[str, MCPConnection] = {}

    async def add_server(self, name: str, command: list[str], env: dict[str, str] | None = None, cwd: str | None = None) -> bool:
        """Adds and connects an MCP server."""
        conn = MCPConnection(name, command, env, cwd)
        if await conn.connect():
            self._connections[name] = conn
            return True
        return False

    async def call(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> str | None:
        """Calls a tool on a specific server."""
        if server_name not in self._connections:
            return None
        res = await self._connections[server_name].call_tool(tool_name, arguments)
        if isinstance(res, dict):
            return json.dumps(res, ensure_ascii=False)
        return res

    def get_all_tools(self) -> list[dict[str, Any]]:
        """Aggregates tools from all connected servers."""
        all_tools = []
        for name, conn in self._connections.items():
            for tool in conn._tools:
                # Prefix tool name with server name to avoid collisions
                prefixed_tool = tool.copy()
                prefixed_tool["name"] = f"mcp_{name}_{tool['name']}"
                prefixed_tool["server_name"] = name
                prefixed_tool["original_name"] = tool["name"]
                all_tools.append(prefixed_tool)
        return all_tools

    async def shutdown(self) -> None:
        """Disconnects all servers."""
        for conn in self._connections.values():
            conn.disconnect()
        self._connections.clear()
