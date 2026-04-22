"""
Coda V4.0 — Swarm Transport Layer (高重要度 #4 & #5)
真正的网络 I/O: WebSocket 服务器/客户端 + 本地 Agent 间 IPC Bridge。

设计参考:
  - 原始 TS `server/directConnectManager.ts`
  - 原始 TS `bridge/replBridge.ts`
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Coroutine, Sequence, TypeVar, Protocol, TYPE_CHECKING

from .swarm import SwarmMessage, SwarmNetwork, SwarmPeer, SwarmRole

logger = logging.getLogger("Coda.transport")


class SwarmServer:
    """
    Swarm WebSocket 服务器。

    作为 Coordinator 节点, 监听连接并处理 Worker 的消息。
    支持任务分发、心跳监测、权限同步。
    """

    def __init__(self, network: SwarmNetwork, host: str = "0.0.0.0", port: int = 9700):
        self.network = network
        self.host = host
        self.port = port
        self._server: asyncio.Server | None = None
        self._clients: dict[str, asyncio.StreamWriter] = {}
        self._handlers: dict[str, Callable[[SwarmMessage], Coroutine[Any, Any, None]]] = {
            "heartbeat": self._handle_heartbeat,
            "result": self._handle_result,
            "task": self._handle_task,
            "permission_grant": self._handle_permission,
        }

    async def start(self) -> None:
        """启动 WebSocket 服务器。"""
        self._server = await asyncio.start_server(
            self._handle_connection,
            self.host,
            self.port,
        )
        logger.info(f"🌐 Swarm server listening on {self.host}:{self.port}")

    async def stop(self) -> None:
        """停止服务器。"""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            for writer in self._clients.values():
                writer.close()
            self._clients.clear()
            logger.info("Swarm server stopped")

    async def broadcast(self, msg: SwarmMessage) -> int:
        """广播消息给所有连接的 Worker, 返回成功发送的数量。"""
        signed = self.network.sign_message(msg)
        data = (signed.to_json() + "\n").encode("utf-8")
        sent = 0
        dead = []
        for peer_id, writer in self._clients.items():
            try:
                writer.write(data)
                await writer.drain()
                sent += 1
            except Exception:
                dead.append(peer_id)
        for d in dead:
            self._clients.pop(d, None)
        return sent

    async def send_to(self, peer_id: str, msg: SwarmMessage) -> bool:
        """定向发送消息给指定节点。"""
        writer = self._clients.get(peer_id)
        if not writer:
            return False
        try:
            signed = self.network.sign_message(msg)
            writer.write((signed.to_json() + "\n").encode("utf-8"))
            await writer.drain()
            return True
        except Exception:
            self._clients.pop(peer_id, None)
            return False

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """处理新的客户端连接。"""
        addr = writer.get_extra_info("peername")
        logger.info(f"Swarm: new connection from {addr}")

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = SwarmMessage.from_json(line.decode("utf-8").strip())
                except Exception:
                    continue

                # 验证签名
                if not self.network.verify_message(msg):
                    logger.warning(f"Swarm: invalid signature from {msg.sender_id}")
                    continue

                # 注册客户端
                if msg.sender_id not in self._clients:
                    self._clients[msg.sender_id] = writer
                    logger.info(f"Swarm: registered peer {msg.sender_id}")

                # 路由到处理器
                handler = self._handlers.get(msg.msg_type)
                if handler:
                    await handler(msg)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"Swarm connection error: {e}")
        finally:
            writer.close()

    async def _handle_heartbeat(self, msg: SwarmMessage) -> None:
        self.network.process_heartbeat(msg)

    async def _handle_result(self, msg: SwarmMessage) -> None:
        task_id = msg.payload.get("task_id")
        if isinstance(task_id, str):
            self.network._results[task_id] = msg.payload
            logger.info(f"Swarm: received result for task {task_id}")

    async def _handle_task(self, msg: SwarmMessage) -> None:
        # Coordinator 收到任务请求, 转发给空闲 Worker
        workers = self.network.get_active_workers()
        if workers:
            target = workers[0]
            msg.receiver_id = target.peer_id
            await self.send_to(target.peer_id, msg)

    async def _handle_permission(self, msg: SwarmMessage) -> None:
        logger.info(f"Swarm: permission granted to {msg.receiver_id}: {msg.payload}")


class SwarmClient:
    """
    Swarm WebSocket 客户端。

    作为 Worker 节点, 连接到 Coordinator 并接收任务。
    """

    def __init__(self, network: SwarmNetwork, host: str = "127.0.0.1", port: int = 9700):
        self.network = network
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._task_handler: Callable[[dict[str, object]], Any] | None = None

    def set_task_handler(self, handler: Callable[[dict[str, object]], Coroutine[Any, Any, Any]]) -> None:
        """注册任务处理回调。"""
        self._task_handler = handler

    async def connect(self) -> bool:
        """连接到 Coordinator。"""
        try:
            self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
            logger.info(f"🌐 Swarm client connected to {self.host}:{self.port}")

            # 发送初始心跳
            heartbeat = self.network.create_heartbeat()
            await self._send(heartbeat)
            return True
        except Exception as e:
            logger.error(f"Swarm connection failed: {e}")
            return False

    async def disconnect(self) -> None:
        """断开连接。"""
        if self._writer:
            self._writer.close()
            self._reader = None
            self._writer = None

    async def listen(self) -> None:
        """监听来自 Coordinator 的消息。"""
        if not self._reader:
            return

        try:
            while True:
                line = await self._reader.readline()
                if not line:
                    break
                try:
                    msg = SwarmMessage.from_json(line.decode("utf-8").strip())
                except Exception:
                    continue

                if not self.network.verify_message(msg):
                    continue

                if msg.msg_type == "task" and self._task_handler:
                    result = await self._task_handler(msg.payload)
                    response = SwarmMessage(
                        sender_id=self.network.agent_id,
                        receiver_id=msg.sender_id,
                        msg_type="result",
                        payload={"task_id": msg.payload.get("task_id"), "result": result},
                    )
                    await self._send(response)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Swarm listen error: {e}")

    async def send_heartbeat(self) -> None:
        """发送心跳。"""
        heartbeat = self.network.create_heartbeat()
        await self._send(heartbeat)

    async def _send(self, msg: SwarmMessage) -> None:
        """发送消息到 Coordinator。"""
        if self._writer:
            signed = self.network.sign_message(msg)
            self._writer.write((signed.to_json() + "\n").encode("utf-8"))
            await self._writer.drain()


# ════════════════════════════════════════════
#  Local Agent Bridge (Pillar: 本机 IPC) (#5)
# ════════════════════════════════════════════

class LocalBridge:
    """
    本地 Agent 间通信桥 (Local IPC Bridge)。

    同一台机器上的多个 Agent 进程通过 Named Pipe / Unix Socket 通信,
    共享权限、交换结果、同步状态。
    """

    def __init__(self, agent_id: str, bridge_dir: str | Path | None = None):
        self.agent_id = agent_id
        # [V5.2] 使用更稳定的路径作为 Workspace Bridge
        if not bridge_dir:
            # 尝试在当前工作区的 agents 目录下创建
            self.bridge_dir = Path("agents") / ".bridge"
        else:
            self.bridge_dir = Path(bridge_dir)
            
        self.bridge_dir.mkdir(parents=True, exist_ok=True)
        self._mailbox = self.bridge_dir / f"{agent_id}.inbox"
        self._registry = self.bridge_dir / "registry.json"

    def register(self) -> None:
        """注册自己到本地 Bridge。"""
        registry = self._load_registry()
        registry[self.agent_id] = {
            "pid": os.getpid(),
            "registered_at": time.time(),
            "mailbox": str(self._mailbox),
        }
        self._save_registry(registry)
        logger.info(f"Bridge: registered {self.agent_id} (PID {os.getpid()})")

    def unregister(self) -> None:
        """注销自己。"""
        registry = self._load_registry()
        registry.pop(self.agent_id, None)
        self._save_registry(registry)
        # 清理 mailbox
        if self._mailbox.exists():
            self._mailbox.unlink()

    def list_agents(self) -> list[dict[str, Any]]:
        """列出所有在线的本地 Agent。"""
        registry = self._load_registry()
        alive = []
        for agent_id, info in registry.items():
            # 检查进程是否还活着
            try:
                os.kill(info.get("pid", 0), 0)
                alive.append({"id": agent_id, **info})
            except (OSError, ProcessLookupError):
                pass  # Agent 已退出
        return alive

    def send(self, target_agent: str, message: dict[str, object]) -> bool:
        """发送消息给本地的另一个 Agent (Pillar: High Integrity IPC)."""
        registry = self._load_registry()
        if target_agent not in registry:
            logger.warning(f"Bridge: target {target_agent} not registered.")
            return False

        target_mailbox = Path(registry[target_agent]["mailbox"])
        msg = {
            "from": self.agent_id,
            "to": target_agent,
            "payload": message,
            "timestamp": time.time(),
        }
        
        try:
            # 物理追加写入 (JSONL 格式)
            with open(target_mailbox, "a", encoding="utf-8") as f:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            logger.debug(f"📬 Message delivered to {target_agent}'s inbox.")
            return True
        except Exception as e:
            logger.error(f"Bridge: failed to deliver to {target_agent}: {e}")
            return False

    def receive(self) -> list[dict[str, object]]:
        """读取并清空自己的收件箱 (Pillar: Finite State IPC)."""
        if not self._mailbox.exists():
            return []

        messages = []
        try:
            # 检查文件大小
            if self._mailbox.stat().st_size == 0:
                return []
                
            content = self._mailbox.read_text(encoding="utf-8").strip()
            if not content:
                self._mailbox.write_text("", encoding="utf-8")
                return []
                
            lines = content.split("\n")
            for line in lines:
                if line.strip():
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            
            # 清空收件箱以实现一次性消费 (Consumable)
            self._mailbox.write_text("", encoding="utf-8")
            logger.debug(f"📥 Received {len(messages)} messages from local bridge.")
        except Exception as e:
            logger.warning(f"Bridge receive failed: {e}")
        return messages

    def _load_registry(self) -> dict[str, Any]:
        if self._registry.exists():
            try:
                return json.loads(self._registry.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Failed to load registry: {e}")
                return {}
        return {}

    def _save_registry(self, data: dict[str, Any]) -> None:
        self._registry.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
