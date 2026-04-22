"""
Coda V6.5 — IDE Bridge (IDE 本地语言服务器桥接)

通过自动检测 IDE 的本地 language_server 进程,提取端口和 CSRF Token,
实时查询用户的模型配额和可用性状态,为 AdvisorEngine 提供真实的
模型路由数据。

核心机制:
  1. 进程检测: 扫描 language_server_windows_x64.exe 进程参数
  2. API 调用: Connect Protocol 调用 GetUserStatus
  3. 配额监控: 解析模型配额、用户 Tier、Prompt Credits
  4. 路由桥接: 为 AdvisorExecutorRouter 提供实时可用模型列表

参考实现:
  - CodaQuotaWatcher (portDetectionService / quotaService)
  - gcli2api (Coda API mode)

安全说明:
  - 仅访问 127.0.0.1 本地回环地址
  - CSRF Token 从进程参数中提取 (IDE 进程可信)
  - SSL 证书为 IDE 自签名, 验证时跳过
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import re
import ssl
import subprocess
import urllib.parse
import urllib.request
import urllib.error
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

logger = logging.getLogger("Coda.ide_bridge")


# ════════════════════════════════════════════
#  数据结构
# ════════════════════════════════════════════

@dataclass
class IDEProcessInfo:
    """IDE 语言服务器进程信息。"""
    pid: int
    extension_port: int          # --extension_server_port (HTTP)
    https_port: int              # --https_server_port (HTTPS/Connect)
    csrf_token: str              # --csrf_token
    extension_csrf_token: str    # --extension_server_csrf_token
    cloud_endpoint: str          # --cloud_code_endpoint
    workspace_id: str            # --workspace_id (if present)
    has_lsp: bool                # --enable_lsp flag present


@dataclass
class ModelQuotaInfo:
    """单个模型的配额信息。"""
    label: str                   # "Claude Sonnet 4.6 (Thinking)"
    model_id: str                # "MODEL_PLACEHOLDER_M35"
    remaining_fraction: float    # 0.0 ~ 1.0
    remaining_percentage: float  # 0 ~ 100
    is_exhausted: bool           # 配额耗尽
    reset_time: str              # ISO 时间字符串
    time_until_reset_seconds: float  # 距重置的秒数


@dataclass
class PromptCreditsInfo:
    """Prompt Credits 额度。"""
    available: int
    monthly: int
    used_percentage: float       # 0 ~ 100
    remaining_percentage: float  # 0 ~ 100


@dataclass
class IDEQuotaSnapshot:
    """IDE 配额快照 — GetUserStatus API 的解析结果。"""
    timestamp: float                        # Unix timestamp
    user_tier: str                          # "Google AI Pro", "Free", etc.
    prompt_credits: Optional[PromptCreditsInfo]
    models: list[ModelQuotaInfo] = field(default_factory=list)
    plan_name: str = ""                     # Plan 名称
    raw_response: dict = field(default_factory=dict, repr=False)  # 原始响应


# ════════════════════════════════════════════
#  进程检测器
# ════════════════════════════════════════════

class IDEProcessDetector:
    """
    检测 Coda IDE 的 language_server 进程,
    提取端口号和 CSRF Token。

    Windows: Get-CimInstance Win32_Process + 正则匹配
    Linux/Mac: ps aux + 正则匹配
    """

    PROCESS_NAME_WIN = "language_server_windows_x64.exe"
    PROCESS_NAME_LINUX = "language_server_linux_x64"
    PROCESS_NAME_MAC = "language_server_macos_x64"

    @classmethod
    def get_process_name(cls) -> str:
        """获取当前平台的 language_server 进程名。"""
        system = platform.system().lower()
        if system == "windows":
            return cls.PROCESS_NAME_WIN
        elif system == "darwin":
            return cls.PROCESS_NAME_MAC
        return cls.PROCESS_NAME_LINUX

    @classmethod
    async def detect(cls) -> list[IDEProcessInfo]:
        """
        异步检测所有活跃的 IDE 语言服务器进程。

        Returns:
            按优先级排序的进程列表 (LSP 进程优先)

        Raises:
            RuntimeError: 如果进程检测命令执行失败
        """
        system = platform.system().lower()
        if system == "windows":
            return await cls._detect_windows()
        return await cls._detect_unix()

    @classmethod
    async def _detect_windows(cls) -> list[IDEProcessInfo]:
        """Windows 平台进程检测。"""
        proc_name = cls.PROCESS_NAME_WIN
        cmd = [
            "powershell", "-NoProfile", "-Command",
            f'Get-CimInstance Win32_Process | Where-Object '
            f'{{$_.Name -like "*language_server*"}} | '
            f'Select-Object ProcessId,CommandLine | ConvertTo-Json'
        ]

        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    cmd, capture_output=True, text=True, timeout=10
                )
            )
        except subprocess.TimeoutExpired:
            logger.error("Process detection timed out")
            raise RuntimeError("IDE process detection timed out after 10s")
        except FileNotFoundError:
            logger.error("PowerShell not found")
            raise RuntimeError("PowerShell is required for IDE process detection on Windows")

        if not result.stdout.strip():
            logger.info("No language_server processes found")
            return []

        try:
            data = json.loads(result.stdout.strip())
        except json.JSONDecodeError as e:
            logger.error("Failed to parse process list: %s", e)
            return []

        if not isinstance(data, list):
            data = [data]

        results: list[IDEProcessInfo] = []
        for item in data:
            cmd_line = item.get("CommandLine") or ""
            pid = item.get("ProcessId", 0)

            if not cls._is_Coda_process(cmd_line):
                continue

            info = cls._parse_command_line(pid, cmd_line)
            if info:
                results.append(info)

        # LSP 进程优先 (workspace-specific, 有 HTTPS Port)
        results.sort(key=lambda x: (not x.has_lsp, -x.https_port))
        logger.info(
            "Detected %d Coda process(es): %s",
            len(results),
            [(p.pid, p.https_port or p.extension_port) for p in results]
        )
        return results

    @classmethod
    async def _detect_unix(cls) -> list[IDEProcessInfo]:
        """Unix/Mac 平台进程检测。"""
        proc_name = cls.get_process_name()
        cmd = ["ps", "aux"]

        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    cmd, capture_output=True, text=True, timeout=10
                )
            )
        except Exception as e:
            logger.error("Unix process detection failed: %s", e)
            raise RuntimeError(f"IDE process detection failed: {e}")

        results: list[IDEProcessInfo] = []
        for line in result.stdout.splitlines():
            if proc_name not in line:
                continue
            if not cls._is_Coda_process(line):
                continue

            # 从 ps 输出提取 PID (第二个字段)
            parts = line.split()
            pid = int(parts[1]) if len(parts) > 1 else 0
            info = cls._parse_command_line(pid, line)
            if info:
                results.append(info)

        results.sort(key=lambda x: (not x.has_lsp, -x.https_port))
        return results

    @staticmethod
    def _is_Coda_process(cmd_line: str) -> bool:
        """判断命令行是否属于 Coda 进程。"""
        lower = cmd_line.lower()
        if re.search(r"--app_data_dir\s+Coda\b", cmd_line, re.I):
            return True
        if "\\Coda\\" in lower or "/Coda/" in lower:
            return True
        return False

    @staticmethod
    def _parse_command_line(pid: int, cmd_line: str) -> Optional[IDEProcessInfo]:
        """从命令行参数中提取端口、CSRF Token 等信息。"""
        ext_port_m = re.search(r"--extension_server_port[=\s]+(\d+)", cmd_line)
        csrf_m = re.search(r"--csrf_token[=\s]+([a-f0-9-]+)", cmd_line, re.I)
        ext_csrf_m = re.search(r"--extension_server_csrf_token[=\s]+([a-f0-9-]+)", cmd_line, re.I)
        https_port_m = re.search(r"--https_server_port[=\s]+(\d+)", cmd_line)
        cloud_m = re.search(r"--cloud_code_endpoint[=\s]+(\S+)", cmd_line)
        workspace_m = re.search(r"--workspace_id[=\s]+(\S+)", cmd_line)
        has_lsp = "--enable_lsp" in cmd_line

        if not csrf_m:
            logger.debug("PID %d: No CSRF token found, skipping", pid)
            return None

        ext_port = int(ext_port_m.group(1)) if ext_port_m else 0
        https_port = int(https_port_m.group(1)) if https_port_m else 0

        return IDEProcessInfo(
            pid=pid,
            extension_port=ext_port,
            https_port=https_port,
            csrf_token=csrf_m.group(1),
            extension_csrf_token=ext_csrf_m.group(1) if ext_csrf_m else "",
            cloud_endpoint=cloud_m.group(1) if cloud_m else "",
            workspace_id=workspace_m.group(1) if workspace_m else "",
            has_lsp=has_lsp,
        )


# ════════════════════════════════════════════
#  语言服务器 API 客户端
# ════════════════════════════════════════════

class LanguageServerClient:
    """
    IDE 语言服务器 Connect Protocol 客户端。

    调用 /exa.language_server_pb.LanguageServerService/GetUserStatus
    获取用户状态和模型配额信息。
    """

    GET_USER_STATUS_PATH = "/exa.language_server_pb.LanguageServerService/GetUserStatus"

    def __init__(self, process_info: IDEProcessInfo):
        self._info = process_info
        self._ssl_ctx = ssl.create_default_context()
        self._ssl_ctx.check_hostname = False
        self._ssl_ctx.verify_mode = ssl.CERT_NONE

    @property
    def connect_port(self) -> int:
        """首选连接端口 (HTTPS > Extension)。"""
        return self._info.https_port or self._info.extension_port

    def _make_request(self, path: str, body: dict, timeout: float = 5.0) -> dict:
        """
        发送 Connect Protocol 请求。

        先尝试 HTTPS, SSL 握手失败时回退到 HTTP。
        """
        payload = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(payload)),
            "Connect-Protocol-Version": "1",
            "X-Codeium-Csrf-Token": self._info.csrf_token,
        }

        # 策略: HTTPS on connect_port → HTTP on extension_port
        attempts = []
        if self._info.https_port:
            attempts.append(("https", self._info.https_port))
        if self._info.extension_port:
            attempts.append(("https", self._info.extension_port))
            attempts.append(("http", self._info.extension_port))

        last_error = None
        for proto, port in attempts:
            url = f"{proto}://127.0.0.1:{port}{path}"
            req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
            try:
                ctx = self._ssl_ctx if proto == "https" else None
                resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
                data = json.loads(resp.read().decode("utf-8"))
                logger.debug("Request succeeded: %s (status=%d)", url, resp.status)
                return data
            except urllib.error.URLError as e:
                msg = str(e).lower()
                if "wrong_version_number" in msg or "ssl" in msg:
                    logger.debug("SSL mismatch at %s, trying next...", url)
                    last_error = e
                    continue
                if "403" in msg or "forbidden" in msg:
                    logger.warning("403 Forbidden at %s (CSRF mismatch?)", url)
                    last_error = e
                    continue
                last_error = e
                logger.debug("Request failed: %s — %s", url, e)
            except Exception as e:
                last_error = e
                logger.debug("Request error: %s — %s", url, e)

        raise ConnectionError(
            f"All {len(attempts)} connection attempts failed. Last error: {last_error}"
        )

    def get_user_status(self) -> dict:
        """调用 GetUserStatus API, 返回原始响应。"""
        body = {
            "metadata": {
                "ideName": "Coda",
                "extensionName": "Coda",
                "ideVersion": "1.0.0",
                "locale": "en",
            }
        }
        return self._make_request(self.GET_USER_STATUS_PATH, body)

    def parse_user_status(self, raw: dict) -> IDEQuotaSnapshot:
        """将 GetUserStatus 原始响应解析为结构化配额快照。"""
        user_status = raw.get("userStatus", {})
        plan_status = user_status.get("planStatus", {})
        plan_info = plan_status.get("planInfo", {})
        user_tier = user_status.get("userTier", {})
        cascade_data = user_status.get("cascadeModelConfigData", {})
        model_configs = cascade_data.get("clientModelConfigs", [])

        # Prompt Credits
        monthly_raw = plan_info.get("monthlyPromptCredits")
        available_raw = plan_status.get("availablePromptCredits")
        prompt_credits = None
        if monthly_raw is not None and available_raw is not None:
            monthly = int(monthly_raw)
            available = int(available_raw)
            if monthly > 0:
                prompt_credits = PromptCreditsInfo(
                    available=available,
                    monthly=monthly,
                    used_percentage=((monthly - available) / monthly) * 100,
                    remaining_percentage=(available / monthly) * 100,
                )

        # Models
        models: list[ModelQuotaInfo] = []
        now = time.time()
        for mc in model_configs:
            quota_info = mc.get("quotaInfo", {})
            if not quota_info:
                continue

            remaining = quota_info.get("remainingFraction", 0)
            reset_time_str = quota_info.get("resetTime", "")

            # 计算距重置的秒数
            try:
                from datetime import datetime, timezone
                reset_dt = datetime.fromisoformat(reset_time_str.replace("Z", "+00:00"))
                time_until_reset = (reset_dt.timestamp() - now)
            except (ValueError, TypeError):
                time_until_reset = 0

            model_alias = mc.get("modelOrAlias", {})
            models.append(ModelQuotaInfo(
                label=mc.get("label", ""),
                model_id=model_alias.get("model", ""),
                remaining_fraction=remaining if remaining is not None else 0,
                remaining_percentage=(remaining * 100) if remaining is not None else 0,
                is_exhausted=(remaining is None or remaining == 0),
                reset_time=reset_time_str,
                time_until_reset_seconds=max(time_until_reset, 0),
            ))

        return IDEQuotaSnapshot(
            timestamp=now,
            user_tier=user_tier.get("name", ""),
            prompt_credits=prompt_credits,
            models=models,
            plan_name=plan_info.get("name", ""),
            raw_response=raw,
        )


# ════════════════════════════════════════════
#  IDE Bridge (主入口)
# ════════════════════════════════════════════

class IDEBridge:
    """
    IDE 桥接器 — Advisor Engine 与 IDE 语言服务器之间的桥梁。

    职责:
      1. 自动检测 IDE 进程, 提取认证信息
      2. 定期拉取配额快照
      3. 提供 is_model_available() 判断模型可用性
      4. 为 AdvisorExecutorRouter 提供模型筛选依据

    用法:
        bridge = await IDEBridge.connect()
        snapshot = bridge.get_latest_snapshot()
        available = bridge.get_available_models()
    """

    _instance: Optional[IDEBridge] = None  # 单例

    def __init__(self):
        self._process_info: Optional[IDEProcessInfo] = None
        self._client: Optional[LanguageServerClient] = None
        self._latest_snapshot: Optional[IDEQuotaSnapshot] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._poll_interval_sec: float = 60.0  # 默认 1 分钟轮询
        self._connected: bool = False
        self._connection_error: Optional[str] = None

    @classmethod
    async def connect(cls) -> IDEBridge:
        """
        工厂方法: 检测 IDE 进程并建立连接。

        Returns:
            已连接的 IDEBridge 实例

        Raises:
            ConnectionError: 无法检测到 IDE 进程
        """
        bridge = cls()
        await bridge._establish_connection()
        return bridge

    @classmethod
    async def get_or_connect(cls) -> IDEBridge:
        """获取现有实例或创建新连接 (单例模式)。"""
        if cls._instance and cls._instance._connected:
            return cls._instance
        cls._instance = await cls.connect()
        return cls._instance

    async def _establish_connection(self) -> None:
        """检测进程并建立 API 连接。"""
        try:
            processes = await IDEProcessDetector.detect()
        except RuntimeError as e:
            self._connection_error = str(e)
            raise ConnectionError(f"IDE process detection failed: {e}")

        if not processes:
            self._connection_error = "No Coda IDE language_server processes found"
            raise ConnectionError(self._connection_error)

        # 优先使用有 HTTPS 端口的 LSP 进程
        selected = processes[0]
        self._process_info = selected
        self._client = LanguageServerClient(selected)

        logger.info(
            "Connected to IDE language server: PID=%d, port=%d, workspace=%s",
            selected.pid,
            self._client.connect_port,
            selected.workspace_id or "(global)",
        )

        # 首次拉取配额
        try:
            await self.refresh_quota()
            self._connected = True
        except Exception as e:
            self._connection_error = f"First quota fetch failed: {e}"
            # 即使第一次拉取失败, 也保持连接 (可能是临时网络问题)
            self._connected = True
            logger.warning("First quota fetch failed, but connection established: %s", e)

    async def refresh_quota(self) -> IDEQuotaSnapshot:
        """
        刷新配额信息 (同步 HTTP 调用, 通过 executor 异步化)。

        Returns:
            最新的配额快照

        Raises:
            ConnectionError: API 调用失败
        """
        if not self._client:
            raise ConnectionError("Not connected to IDE language server")

        loop = asyncio.get_running_loop()
        try:
            raw = await loop.run_in_executor(None, self._client.get_user_status)
        except Exception as e:
            raise ConnectionError(f"GetUserStatus failed: {e}")

        snapshot = self._client.parse_user_status(raw)
        self._latest_snapshot = snapshot

        logger.info(
            "Quota refreshed: tier=%s, models=%d, credits=%s/%s",
            snapshot.user_tier,
            len(snapshot.models),
            snapshot.prompt_credits.available if snapshot.prompt_credits else "N/A",
            snapshot.prompt_credits.monthly if snapshot.prompt_credits else "N/A",
        )
        return snapshot

    def get_latest_snapshot(self) -> Optional[IDEQuotaSnapshot]:
        """获取最新的配额快照 (缓存)。"""
        return self._latest_snapshot

    def get_available_models(self) -> list[ModelQuotaInfo]:
        """获取所有未耗尽配额的模型列表。"""
        if not self._latest_snapshot:
            return []
        return [m for m in self._latest_snapshot.models if not m.is_exhausted]

    def is_model_available(self, model_label_or_id: str) -> bool:
        """
        检查指定模型是否可用 (配额未耗尽)。

        Args:
            model_label_or_id: 模型标签或 ID (部分匹配)
        """
        if not self._latest_snapshot:
            return False
        key = model_label_or_id.lower()
        for m in self._latest_snapshot.models:
            if key in m.label.lower() or key in m.model_id.lower():
                return not m.is_exhausted
        return False

    def get_model_quota(self, model_label_or_id: str) -> Optional[ModelQuotaInfo]:
        """获取指定模型的配额信息。"""
        if not self._latest_snapshot:
            return None
        key = model_label_or_id.lower()
        for m in self._latest_snapshot.models:
            if key in m.label.lower() or key in m.model_id.lower():
                return m
        return None

    # ── 轮询控制 ──

    async def start_polling(self, interval_sec: float = 60.0) -> None:
        """启动后台配额轮询。"""
        self._poll_interval_sec = interval_sec
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()

        self._poll_task = asyncio.create_task(self._polling_loop())
        logger.info("Quota polling started (interval=%ds)", interval_sec)

    async def stop_polling(self) -> None:
        """停止轮询。"""
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
            logger.info("Quota polling stopped")

    async def _polling_loop(self) -> None:
        """轮询循环 — 定期刷新配额。"""
        consecutive_errors = 0
        max_consecutive_errors = 5

        while True:
            try:
                await asyncio.sleep(self._poll_interval_sec)
                await self.refresh_quota()
                consecutive_errors = 0
            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_errors += 1
                logger.warning(
                    "Quota poll error (%d/%d): %s",
                    consecutive_errors, max_consecutive_errors, e
                )
                if consecutive_errors >= max_consecutive_errors:
                    logger.error("Max polling errors reached, stopping polling")
                    break
                # 指数退避 (5s → 10s → 20s → 40s → 80s)
                backoff = min(5 * (2 ** (consecutive_errors - 1)), 120)
                await asyncio.sleep(backoff)

    # ── 信息/诊断 ──

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def process_info(self) -> Optional[IDEProcessInfo]:
        return self._process_info

    def get_status_summary(self) -> dict[str, Any]:
        """获取完整的状态摘要 (用于诊断)。"""
        summary: dict[str, Any] = {
            "connected": self._connected,
            "error": self._connection_error,
        }

        if self._process_info:
            summary["process"] = {
                "pid": self._process_info.pid,
                "extension_port": self._process_info.extension_port,
                "https_port": self._process_info.https_port,
                "workspace_id": self._process_info.workspace_id,
                "cloud_endpoint": self._process_info.cloud_endpoint,
                "has_lsp": self._process_info.has_lsp,
            }

        if self._latest_snapshot:
            s = self._latest_snapshot
            summary["quota"] = {
                "user_tier": s.user_tier,
                "plan_name": s.plan_name,
                "total_models": len(s.models),
                "available_models": len(self.get_available_models()),
                "prompt_credits": {
                    "available": s.prompt_credits.available,
                    "monthly": s.prompt_credits.monthly,
                    "remaining_pct": round(s.prompt_credits.remaining_percentage, 1),
                } if s.prompt_credits else None,
                "models": [
                    {
                        "label": m.label,
                        "model_id": m.model_id,
                        "remaining_pct": round(m.remaining_percentage, 1),
                        "exhausted": m.is_exhausted,
                    }
                    for m in s.models
                ],
            }

        return summary

    async def dispose(self) -> None:
        """释放资源。"""
        await self.stop_polling()
        self._connected = False
        self._client = None
        if IDEBridge._instance is self:
            IDEBridge._instance = None
        logger.info("IDEBridge disposed")
