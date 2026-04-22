"""
Coda V5.1 — LLM Caller (Pillar 1)
真正的大模型调用接口: 对接 Gemini / Claude / OpenAI，并集成 Anthropic 混合缓存。
"""

from __future__ import annotations

import asyncio
import base64
import gzip
import json
import logging
import os
import re
import sqlite3
import time
import urllib.parse
import urllib.request
import urllib.error
import requests
from collections.abc import Sequence, Mapping, Callable
from typing import Any, cast, Protocol, runtime_checkable, override, TYPE_CHECKING
from dotenv import load_dotenv

load_dotenv()

from .base_types import (
    BaseLLM,
    LLMResponse,
)

# ── V7.0: 密钥加载引擎 ──
_secrets_cache: dict[str, str] = {}
def get_secret(key: str, default: str = "") -> str:
    """按优先级从 secrets.json 或 环境变量加载密钥。"""
    global _secrets_cache
    if not _secrets_cache:
        file_path = os.path.join(os.path.dirname(__file__), "secrets.json")
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    _secrets_cache = json.load(f)
            except Exception as e:
                logging.getLogger("Coda.llm").warning(f"Failed to load secrets.json: {e}")
    
    return _secrets_cache.get(key) or os.getenv(key) or default

# [Hermes] 响应协议定义: 用于打破对供应商 SDK 的硬依赖并解决 lint 错误
@runtime_checkable
class GeminiCandidateProtocol(Protocol):
    index: int
    content: Any # From SDK

@runtime_checkable
class GeminiResponseProtocol(Protocol):
    candidates: list[Any]
    usage_metadata: Any

@runtime_checkable
class ClaudeContentProtocol(Protocol):
    type: str
    text: str | None = None
    id: str | None = None
    input: dict[str, object] | None = None

@runtime_checkable
class ClaudeResponseProtocol(Protocol):
    content: list[Any]
    usage: Any
    stop_reason: str

@runtime_checkable
class OpenAIChoiceProtocol(Protocol):
    index: int
    message: Any
    finish_reason: str

@runtime_checkable
class OpenAIResponseProtocol(Protocol):
    choices: list[Any]
    usage: Any

logger = logging.getLogger("Coda.llm")

# 重试配置 (V5.0 Orchestrator Pattern)
MAX_RETRIES = 5
BASE_DELAY = 0.5
MAX_DELAY = 4.0


# ── V7.1: OAuth Constants (Environment Driven) ──
ANTIGRAVITY_CLIENT_ID = get_secret("ANTIGRAVITY_CLIENT_ID", "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com")
ANTIGRAVITY_CLIENT_SECRET = get_secret("ANTIGRAVITY_CLIENT_SECRET", "YOUR_CLIENT_SECRET_HERE")
CLIENT_ID = get_secret("CLIENT_ID", "681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com")
CLIENT_SECRET = get_secret("CLIENT_SECRET", "YOUR_CLIENT_SECRET_HERE")

class GeminiCaller(BaseLLM):
    """Google Gemini API 调用器。"""

    _model_name: str
    api_key: str
    _client: Any
    _owner_identity: str = "unknown"

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or get_secret("GEMINI_API_KEY")
        self._model_name = model or get_secret("DEFAULT_MODEL_NAME", "gemini-2.0-flash")
        self._client = None
        self._owner_identity = get_secret("Coda_AGENT_IDENTITY", "unknown")

    @property
    @override
    def owner_identity(self) -> str:
        """返回探测到的认证者身份。"""
        return self._owner_identity

    @property
    @override
    def model_name(self) -> str:
        # ── V6.5: Model ID Mapping ──
        # 将 Coda 内部的 High/Low ID 映射为真实的提供商 ID
        # 如果是 2026 年，gemini-3.1-pro 可能是真实 ID，
        # 但我们保留映射表以应对各种提供商协议差异。
        mapping = {
            "gemini-3.1-pro-high": "gemini-3.1-pro",
            "gemini-3.1-pro-low": "gemini-3.1-pro",
            "gemini-3.1-flash-image": "gemini-3.1-flash",
        }
        return mapping.get(self._model_name, self._model_name)

    def _ensure_client(self) -> None:
        if self._client is None:
            try:
                import importlib
                genai = importlib.import_module("google.genai")
                auth = importlib.import_module("google.auth")
                
                # ── V6.5: 身份探测 ──
                # 尝试从凭证中探测当前用户 Email (DID)
                try:
                    creds, _ = auth.default()
                    if hasattr(creds, "service_account_email"):
                        self._owner_identity = f"did:svc:{creds.service_account_email}"
                    elif hasattr(creds, "signer_email") and creds.signer_email:
                        self._owner_identity = f"did:emp:{creds.signer_email}"
                except Exception:
                    pass

                # ── V6.5: 支持 IDE 集成鉴权 ──
                # 如果没有 API Key，尝试使用环境内置鉴权 (ADC / IDE 自动透传)
                # 凡是在 Coda 智能体环境下 (Coda_AGENT=1)，默认允许尝试免 Key 调用 (期待 IDE 代理拦截)
                if not self.api_key and (
                    os.getenv("Coda_IDE_GOOGLE_AUTH") == "true" or 
                    os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or
                    os.getenv("Coda_AGENT") == "1"
                ):
                    logger.info("Using Integrated Auth / Coda Agent identity (Keyless).")
                    # genai.Client 不传 api_key 且 vertexai=True 则会自动寻找凭证或走 IDE 代理
                    self._client = genai.Client(vertexai=True, project=os.getenv("GOOGLE_CLOUD_PROJECT"))
                else:
                    self._client = genai.Client(api_key=self.api_key)
            except ImportError:
                raise ImportError("请安装 google-genai: pip install google-genai")

    @override
    async def call(
        self,
        messages: Sequence[Mapping[str, object]],
        tools: Sequence[Mapping[str, object]] | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """调用 Gemini API。"""
        self._ensure_client()
        try:
            import importlib
            types = importlib.import_module("google.genai.types")
        except (ImportError, ModuleNotFoundError):
            # 如果在运行时仍然出错 (例如 _ensure_client 之后环境变勒)，提供友好提示
            raise ImportError("运行时环境缺少 google-genai 库。")

        contents: list[Any] = []
        system_instruction: str | None = None

        for msg in messages:
            role = str(msg.get("role", "user"))
            content = msg.get("content", "")

            if role == "system":
                system_instruction = str(content)
                continue

            if role in ("model", "assistant"):
                parts: list[Any] = [types.Part.from_text(text=str(content))] if isinstance(content, str) else cast(Any, content)
                contents.append(types.Content(role="model", parts=parts))
            elif role == "tool":
                tool_results = json.loads(str(content)) if isinstance(content, str) else content
                if isinstance(tool_results, list):
                    tool_parts: list[Any] = []
                    for tr in cast("list[dict[str, Any]]", tool_results):
                        tool_parts.append(types.Part.from_function_response(
                            name=str(tr.get("tool_name", "unknown")),
                            response={"result": tr.get("result", "")},
                        ))
                    contents.append(types.Content(role="user", parts=tool_parts))
            else:
                user_parts: list[Any] = []
                if isinstance(content, list):
                    for item in cast("list[Any]", content):
                        if isinstance(item, str):
                            user_parts.append(types.Part.from_text(text=item))
                        elif isinstance(item, dict):
                            if item.get("type") == "image":
                                user_parts.append(types.Part.from_bytes(
                                    data=base64.b64decode(str(item["source"]["data"])),
                                    mime_type=str(item["source"]["media_type"]),
                                ))
                else:
                    user_parts = [types.Part.from_text(text=str(content))]
                contents.append(types.Content(role="user", parts=user_parts))

        config = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_instruction,
            tools=cast(Any, list(tools)) if tools else None,
        )

        for attempt in range(MAX_RETRIES):
            try:
                # Use getattr to safely access SDK methods while remaining zero-debt
                models = getattr(self._client, "models")
                response = await asyncio.to_thread(
                    models.generate_content,
                    model=self.model_name,
                    contents=contents,
                    config=config,
                )
                return self._parse_response(response)
            except Exception as e:
                logger.warning(f"Gemini attempt {attempt+1} failed: {e}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(min(BASE_DELAY * (2 ** attempt), MAX_DELAY))
                else:
                    raise

        return LLMResponse(text="Error", model=self.model_name)

    def _parse_response(self, response: Any) -> LLMResponse:
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        res = cast(GeminiResponseProtocol, response)

        if res.candidates:
            for candidate in res.candidates:
                content = getattr(candidate, "content", None)
                if content:
                    parts = getattr(content, "parts", [])
                    for part in parts:
                        if hasattr(part, "text") and part.text:
                            text_parts.append(str(part.text))
                        if hasattr(part, "function_call") and part.function_call:
                            fc = part.function_call
                            tool_calls.append({
                                "name": str(fc.name),
                                "arguments": dict(fc.args or {}),
                            })

        um = res.usage_metadata
        return LLMResponse(
            text="\n".join(text_parts),
            tool_calls=tool_calls,
            raw=response,
            input_tokens=int(getattr(um, "prompt_token_count", 0) or 0),
            output_tokens=int(getattr(um, "candidates_token_count", 0) or 0),
            cache_tokens=int(getattr(um, "cached_content_token_count", 0) or 0),
            model=self.model_name,
        )


class ClaudeCaller(BaseLLM):
    """Anthropic Claude API 调用器。"""

    _model_name: str
    api_key: str
    _client: Any

    def __init__(self, api_key: str | None = None, model: str | None = None):
        # IDE 环境 fallback: ANTHROPIC_API_KEY → ANTHROPIC_AUTH_TOKEN
        self.api_key = (
            api_key
            or get_secret("ANTHROPIC_API_KEY")
            or get_secret("ANTHROPIC_AUTH_TOKEN")
        )
        self._model_name = model or get_secret("DEFAULT_MODEL_NAME", "claude-3-5-sonnet-20241022")
        self._client = None
        
        # IDE Interception 关键修复: 
        # 如果模型是 IDE 内网套餐,必须将 base_url 设为默认 (None/api.anthropic.com)
        # 否则类似 api.moonshot.cn 会导致流量绕过 IDE 的底层网络拦截，从而出现 401 错误。
        self._force_default_url = self._model_name.startswith("MODEL_PLACEHOLDER_")

    @property
    @override
    def model_name(self) -> str:
        return self._model_name

    def _ensure_client(self) -> None:
        if self._client is None:
            try:
                from anthropic import AsyncAnthropic # type: ignore
                kwargs = {"api_key": self.api_key}
                # 如果是 IDE 专属，强制 override base_url 绕过 os.environ["ANTHROPIC_BASE_URL"]
                # 这样流量才会经过标准的 api.anthropic.com，从而被 IDE 底层安全劫持拦截!
                if getattr(self, "_force_default_url", False):
                    kwargs["base_url"] = "https://api.anthropic.com/"
                
                self._client = AsyncAnthropic(
                    api_key=self.api_key,
                    base_url=kwargs.get("base_url")
                )
            except ImportError:
                raise ImportError("请安装 anthropic (pip install anthropic)")

    @override
    async def call(
        self,
        messages: Sequence[Mapping[str, object]],
        tools: Sequence[Mapping[str, object]] | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        self._ensure_client()
        
        system_text: str = ""
        api_messages: list[dict[str, Any]] = []

        for msg in messages:
            role = str(msg.get("role", "user"))
            content = msg.get("content", "")
            if role == "system":
                system_text = str(content)
            else:
                formatted_role = "assistant" if role in ("model", "assistant") else "user"
                api_messages.append({"role": formatted_role, "content": content})

        kwargs: dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": self._model_max_tokens(),
            "temperature": temperature,
            "messages": api_messages,
        }

        if system_text:
            kwargs["system"] = [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}]

        if tools:
            kwargs["tools"] = list(tools)

        for attempt in range(MAX_RETRIES):
            try:
                msgs = getattr(self._client, "messages")
                response = await msgs.create(**kwargs)
                return self._parse_response(response)
            except Exception as e:
                logger.warning(f"Claude attempt {attempt+1} failed: {e}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(min(BASE_DELAY * (2 ** attempt), MAX_DELAY))
                else:
                    raise

        return LLMResponse(text="Error", model=self.model_name)

    def _model_max_tokens(self) -> int:
        """根据模型名称动态决定 max_tokens 上限。"""
        name = self.model_name.lower()
        if any(k in name for k in ("claude-3-7", "claude-4", "sonnet-4", "opus")):
            return 32768
        if any(k in name for k in ("claude-3-5", "sonnet")):
            return 16384
        return 8192  # haiku / 小模型

    def _parse_response(self, response: Any) -> LLMResponse:
        res = cast(ClaudeResponseProtocol, response)
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []

        for block in res.content:
            if block.type == "text":
                text_parts.append(str(block.text or ""))
            elif block.type == "tool_use":
                tool_calls.append({
                    "name": str(getattr(block, "name", "unknown")),
                    "arguments": block.input or {},
                })

        usage = res.usage
        return LLMResponse(
            text="\n".join(text_parts),
            tool_calls=tool_calls,
            raw=response,
            input_tokens=int(getattr(usage, "input_tokens", 0)),
            output_tokens=int(getattr(usage, "output_tokens", 0)),
            cache_tokens=int(getattr(usage, "cache_read_input_tokens", 0)),
            model=self.model_name,
            finish_reason=res.stop_reason,
        )


class OpenAICaller(BaseLLM):
    """OpenAI API 调用器。"""

    _model_name: str
    api_key: str
    _client: Any

    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None):
        self.api_key = api_key or get_secret("OPENAI_API_KEY")
        self._model_name = model or get_secret("DEFAULT_MODEL_NAME", "gpt-4o")
        self._base_url = base_url
        self._client = None

    @property
    @override
    def model_name(self) -> str:
        return self._model_name

    def _ensure_client(self) -> None:
        if self._client is None:
            try:
                import importlib
                openai = importlib.import_module("openai")
                self._client = openai.AsyncOpenAI(
                    api_key=self.api_key,
                    base_url=self._base_url
                )
            except (ImportError, ModuleNotFoundError):
                raise ImportError("请安装 openai")

    @override
    async def call(
        self,
        messages: Sequence[Mapping[str, object]],
        tools: Sequence[Mapping[str, object]] | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        self._ensure_client()
        api_messages = []
        for msg in messages:
            role = "assistant" if str(msg.get("role")) == "model" else str(msg.get("role", "user"))
            api_messages.append({"role": role, "content": str(msg.get("content", ""))})

        kwargs: dict[str, Any] = {
            "model": self.model_name,
            "messages": api_messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = list(tools)

        for attempt in range(MAX_RETRIES):
            try:
                chat = getattr(self._client, "chat")
                response = await chat.completions.create(**kwargs)
                return self._parse_response(response)
            except Exception as e:
                logger.warning(f"OpenAI attempt {attempt+1} failed: {e}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(min(BASE_DELAY * (2 ** attempt), MAX_DELAY))
                else:
                    raise

        return LLMResponse(text="Error", model=self.model_name)

    def _parse_response(self, response: Any) -> LLMResponse:
        res = cast(OpenAIResponseProtocol, response)
        text = ""
        tool_calls: list[dict[str, Any]] = []

        if res.choices:
            msg = res.choices[0].message
            text = str(getattr(msg, "content", "") or "")
            otc = getattr(msg, "tool_calls", None)
            if otc:
                for tc in cast("list[Any]", otc):
                    func = getattr(tc, "function", None)
                    if func:
                        tool_calls.append({
                            "name": str(func.name),
                            "arguments": json.loads(str(func.arguments)),
                        })

        usage = res.usage
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            raw=response,
            input_tokens=int(getattr(usage, "prompt_tokens", 0)),
            output_tokens=int(getattr(usage, "completion_tokens", 0)),
            model=self.model_name,
        )


def get_token_counter(model_name: str) -> Callable[[Sequence[Mapping[str, object]]], int]:
    """
    Returns a token counter function for Pillar 23.
    """
    def _counter(messages: Sequence[Mapping[str, object]]) -> int:
        total = sum(len(str(m.get("content", ""))) for m in messages)
        return total // 3
    return _counter


class OllamaCaller(OpenAICaller):
    """Ollama 本地 API 调用器 (OpenAI 兼容)。"""

    def __init__(self, model: str | None = None):
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        m = model or os.getenv("OLLAMA_MODEL_NAME") or os.getenv("DEFAULT_MODEL_NAME", "qwen3.5:2b")
        super().__init__(api_key="ollama", model=m, base_url=base_url)

    @override
    async def call(
        self,
        messages: Sequence[Mapping[str, object]],
        tools: Sequence[Mapping[str, object]] | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """调用本地 Ollama。"""
        return await super().call(messages, tools, temperature)


# ════════════════════════════════════════════════════════════
#  Coda Cloud Caller — IDE 登录账号内置模型直连
# ════════════════════════════════════════════════════════════

# Coda IDE 专用 OAuth 凭证 (从 secrets.json 或环境变量读取)
_AG_CLIENT_ID = get_secret("GOOGLE_CLIENT_ID", "YOUR_CLIENT_ID_HERE")
_AG_CLIENT_SECRET = get_secret("GOOGLE_CLIENT_SECRET", "YOUR_CLIENT_SECRET_HERE")
_AG_API_URL = "https://cloudcode-pa.googleapis.com"
_AG_USER_AGENT = "antigravity/1.22.2 windows/amd64"
# IDE 状态数据库候选路径 (V7.1: 动态探测)
_IDE_STATE_DB_CANDIDATES = [
    os.path.expandvars(r"%APPDATA%\Antigravity\User\globalStorage\state.vscdb"),
    os.path.expandvars(r"%APPDATA%\Cursor\User\globalStorage\state.vscdb"),
    os.path.expandvars(r"%APPDATA%\Windsurf\User\globalStorage\state.vscdb"),
    os.path.expandvars(r"%APPDATA%\Trae\User\globalStorage\state.vscdb"),
    os.path.expandvars(r"%APPDATA%\Kiro\User\globalStorage\state.vscdb"),
    os.path.expandvars(r"%APPDATA%\Qoder\User\globalStorage\state.vscdb"),
    os.path.expandvars(r"%APPDATA%\Code - Insiders\User\globalStorage\state.vscdb"),
    os.path.expandvars(r"%APPDATA%\Code\User\globalStorage\state.vscdb"),
    os.path.expandvars(r"%APPDATA%\Coda\User\globalStorage\state.vscdb"),
]

def _get_ide_candidates() -> list[tuple[str, str]]:
    """返回 (IDE名称, 数据库路径) 的候选列表。"""
    names = ["Antigravity", "Cursor", "Trae", "Windsurf", "QClaw", "Qoder", "Code - Insiders", "Code"]
    candidates = []
    for name in names:
        path = os.path.expandvars(rf"%APPDATA%\{name}\User\globalStorage\state.vscdb")
        if os.path.exists(path):
            candidates.append((name, path))
    return candidates

# IDE 占位符 → 真实模型名映射
_PLACEHOLDER_MODEL_MAP: dict[str, str] = {
    "model_placeholder_google": "gemini-3-flash-agent",
    "model_placeholder_anthropic": "claude-sonnet-4-6",
    "model_placeholder_ollama": "gemini-3.1-pro-high",
    "model_placeholder_m35": "claude-sonnet-4-6",
    "model_placeholder_m26": "gemini-3.1-pro-high",
    "model_placeholder_gemini-2.0-flash": "gemini-3-flash-agent",
    "model_placeholder_gemini-1.5-flash": "gemini-3-flash-agent",
    "model_placeholder_gemini-flash-latest": "gemini-3-flash-agent",
    "model_placeholder_gemini-1.5-pro": "gemini-3.1-pro-high",
    "model_placeholder_claude-3-5-sonnet": "claude-sonnet-4-6",
    "model_placeholder_m37": "gemini-3.1-pro-low",
    "model_placeholder_m36": "gemini-3-flash-agent",
    "model_placeholder_m47": "claude-sonnet-4-6",
}


class _CodaTokenCache:
    """OAuth token cache — 从 IDE state.vscdb 提取 refresh_token 并管理 access_token 生命周期。"""

    def __init__(self) -> None:
        self._access_token: str = ""
        self._expires_at: float = 0.0
        self._project_id: str = ""
        self._refresh_token: str = ""
        self._bonded_ide: str = "Unknown"
        self._active_client_id: str = ANTIGRAVITY_CLIENT_ID
        self._active_client_secret: str = ANTIGRAVITY_CLIENT_SECRET
        self._lock = asyncio.Lock()

    def _extract_refresh_token(self) -> str:
        """提取 Google OAuth refresh_token: 优先从环境变量获取，其次从所有已安装 IDE 扫描。"""
        # 1. 优先使用环境变量
        env_token = os.getenv("GOOGLE_REFRESH_TOKEN")
        if env_token:
            logger.info("🔑 [IDE] Using refresh_token from GOOGLE_REFRESH_TOKEN env var.")
            return env_token

        # 2. 扫描 gcli2api 存储 (800% 增强)
        gcli_db = r"D:\ai\docs\gcli2api\creds\credentials.db"
        if os.path.exists(gcli_db):
            logger.debug("🔍 [IDE] Checking gcli2api storage...")
            try:
                conn = sqlite3.connect(gcli_db)
                try:
                    for table in ["antigravity_credentials", "credentials"]:
                        # 检查表是否存在
                        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
                        if not cursor.fetchone(): continue
                        
                        rows = conn.execute(f"SELECT credential_data FROM {table}").fetchall()
                        for row in rows:
                            try:
                                data = json.loads(row[0])
                                token = data.get("refresh_token")
                                if token:
                                    self._verify_token_sync(token)
                                    logger.info(f"📂 [IDE] Successfully bonded with gcli2api ({table}) credentials.")
                                    self._bonded_ide = f"gcli2api_{table}"
                                    return token
                            except Exception: continue
                finally:
                    conn.close()
            except Exception as e:
                logger.debug(f"⚠️ [IDE] gcli2api scan failed: {e}")

        # 3. 扫描所有 IDE 数据库
        candidates = _get_ide_candidates()
        
        keys = [
            "jetskiStateSync.agentManagerInitState",
            "google.agentManagerInitState",
            "cursor.agentManagerInitState",
        ]

        last_error = None
        for ide_name, db_path in candidates:
            logger.debug(f"🔍 [IDE] Checking {ide_name} storage...")
            try:
                conn = sqlite3.connect(db_path)
                try:
                    row = None
                    for key in keys:
                        r = conn.execute("SELECT value FROM ItemTable WHERE key=?", (key,)).fetchone()
                        if r:
                            row = r
                            break
                    
                    if not row:
                        continue
                    
                    decoded = base64.b64decode(row[0])
                    text = decoded.decode("utf-8", errors="replace")
                    tokens = re.findall(r"1//[A-Za-z0-9_\-]{40,}", text)
                    if tokens:
                        refresh_token = tokens[0]
                        # ⚠️ [V7.1] 立即验证 Token 是否可用
                        try:
                            self._verify_token_sync(refresh_token)
                            logger.info(f"📂 [IDE] Successfully bonded with {ide_name} credentials.")
                            self._bonded_ide = ide_name
                            return refresh_token
                        except Exception as ve:
                            logger.warning(f"⚠️ [IDE] {ide_name} token found but invalid: {ve}")
                            last_error = ve
                            continue
                finally:
                    conn.close()
            except Exception as e:
                logger.debug(f"⚠️ [IDE] Failed to read {ide_name} DB: {e}")
                last_error = e

        sources = ["GOOGLE_REFRESH_TOKEN", "gcli2api"] + [c[0] for c in candidates]
        raise RuntimeError(f"Could not find valid credentials in any source: {sources}. Last error: {last_error}")

    def _verify_token_sync(self, refresh_token: str):
        """同步验证 refresh_token 是否能获取 access_token (尝试多种 Client ID)。"""
        last_err = None
        # 尝试 Antigravity 和 Standard 两种 Client ID
        for cid, csec in [(ANTIGRAVITY_CLIENT_ID, ANTIGRAVITY_CLIENT_SECRET), (CLIENT_ID, CLIENT_SECRET)]:
            data = {
                "client_id": cid,
                "client_secret": csec,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
            try:
                import urllib.request
                import urllib.parse
                import json
                
                req = urllib.request.Request(
                    "https://oauth2.googleapis.com/token",
                    data=urllib.parse.urlencode(data).encode("utf-8"),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                with urllib.request.urlopen(req, timeout=10) as f:
                    res = json.loads(f.read().decode("utf-8"))
                    if "access_token" in res:
                        # ⚠️ [V7.1] 记录当前成功的 Client ID
                        self._active_client_id = cid
                        self._active_client_secret = csec
                        return
            except Exception as e:
                last_err = e
                continue
        
        raise RuntimeError(f"Refresh failed for all known client IDs. Last error: {last_err}")

    def _refresh_access_token_sync(self) -> dict[str, Any]:
        """同步刷新 access_token (在 executor 中运行)。"""
        data = urllib.parse.urlencode({
            "client_id": self._active_client_id,
            "client_secret": self._active_client_secret,
            "refresh_token": self._refresh_token,
            "grant_type": "refresh_token",
        }).encode()
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token", data=data, method="POST"
        )
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())

    def _load_code_assist_sync(self, access_token: str) -> dict[str, Any]:
        """同步获取 project_id 和 tier (在 executor 中运行)。"""
        url = f"{_AG_API_URL}/v1internal:loadCodeAssist"
        payload = json.dumps({"metadata": {"ideType": "ANTIGRAVITY"}}).encode()
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {access_token}")
        req.add_header("User-Agent", _AG_USER_AGENT)
        last_err = None
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw = resp.read()
                    # 检查是否是 gzip
                    if raw[:2] == b"\x1f\x8b":
                        import gzip
                        raw = gzip.decompress(raw)
                    data = json.loads(raw.decode())
                    return data
            except urllib.error.HTTPError as e:
                err_body = e.read()
                try:
                    if err_body[:2] == b"\x1f\x8b":
                        import gzip
                        err_body = gzip.decompress(err_body)
                    err_msg = err_body.decode()
                except:
                    err_msg = str(err_body)
                logger.warning("CodaCloud attempt %d/5 HTTP %d: %s", attempt + 1, e.code, err_msg)
                if e.code in [404, 403, 401]:
                    raise RuntimeError(f"Coda API error {e.code}: {err_msg}")
                last_err = e
            except Exception as e:
                logger.warning("CodaCloud attempt %d/5 error: %s", attempt + 1, e)
                last_err = e
            time.sleep(1) # 重试等待
            
        if last_err:
            raise last_err
        return {}

    async def ensure_valid(self) -> tuple[str, str]:
        """
        确保 access_token 有效, 返回 (access_token, project_id)。
        如果已缓存且未过期, 直接返回; 否则执行 refresh 流程。
        """
        async with self._lock:
            # 缓存有效 (提前 3 分钟刷新)
            if self._access_token and time.time() < (self._expires_at - 180):
                return self._access_token, self._project_id

            loop = asyncio.get_running_loop()

            # 1. 提取 refresh_token (仅首次)
            if not self._refresh_token:
                self._refresh_token = await loop.run_in_executor(
                    None, self._extract_refresh_token
                )
                logger.info("Extracted IDE refresh_token (len=%d)", len(self._refresh_token))

            # 2. 刷新 access_token
            result = await loop.run_in_executor(None, self._refresh_access_token_sync)
            self._access_token = result["access_token"]
            self._expires_at = time.time() + int(result.get("expires_in", 3600))
            logger.info(
                "Refreshed Coda access_token (expires_in=%ds)",
                result.get("expires_in", 3600),
            )

            # 3. 获取 project_id (仅首次或失效时)
            if not self._project_id:
                code_assist = await loop.run_in_executor(
                    None, self._load_code_assist_sync, self._access_token
                )
                self._project_id = code_assist.get("cloudaicompanionProject", "")
                tier = code_assist.get("paidTier", {}).get("id", "unknown")
                logger.info(
                    "Loaded project_id=%s, tier=%s", self._project_id, tier
                )
                if not self._project_id:
                    raise RuntimeError(
                        "loadCodeAssist did not return cloudaicompanionProject"
                    )

            return self._access_token, self._project_id

    async def get_status(self) -> dict[str, Any]:
        """获取当前 IDE 代理的身份与额度概况。"""
        try:
            token, project = await self.ensure_valid()
            loop = asyncio.get_running_loop()
            info = await loop.run_in_executor(None, self._load_code_assist_sync, token)
            
            # 提取额度信息 (800% 增强)
            paid_tier = info.get("paidTier", {})
            available_credits = paid_tier.get("availableCredits", []) if isinstance(paid_tier, dict) else []
            credit_amount = None
            if available_credits and isinstance(available_credits, list):
                credit_amount = available_credits[0].get("creditAmount")

            return {
                "is_active": True,
                "ide": self._bonded_ide,
                "project_id": project,
                "tier": info.get("paidTier", {}).get("id", "unknown"),
                "credit_amount": credit_amount,
                "raw": info,
                "models": ["gemini-2.0-flash", "gemini-2.0-pro", "claude-3-5-sonnet"]
            }
        except Exception as e:
            return {"is_active": False, "error": str(e)}

# 模块级单例
_ag_token_cache = _CodaTokenCache()

async def get_ag_status() -> dict[str, Any]:
    return await _ag_token_cache.get_status()


class CodaCloudCaller(BaseLLM):
    """
    Coda Cloud API Caller — 通过 IDE 登录凭证直连 Google Coda API。

    认证链路:
      state.vscdb → refresh_token → access_token → v1internal:generateContent

    支持所有 IDE 内置模型 (Claude / Gemini / etc.)，统一使用 Gemini 格式响应。
    """

    def __init__(self, model: str) -> None:
        raw = model.lower()
        self._raw_model = model
        self._model_name = _PLACEHOLDER_MODEL_MAP.get(raw, raw)

    @property
    @override
    def model_name(self) -> str:
        return self._model_name

    @property
    @override
    def owner_identity(self) -> str:
        return "ide:Coda-cloud"

    # 免费 Gemini 模型不需要 credits；其余模型需要消耗 GOOGLE_ONE_AI credits
    _FREE_MODELS = frozenset({
        "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-flash-thinking",
        "gemini-3.0-flash",
        "gemini-3.1-flash-lite", "gemini-3.1-flash-image",
    })

    def _needs_credits(self) -> bool:
        return self._model_name not in self._FREE_MODELS

    @staticmethod
    def _decode_raw(raw: bytes) -> str:
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", errors="replace")

    def _generate_content_sync(
        self, access_token: str, project_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """同步 HTTP 调用 generateContent (在 executor 中)。"""
        import requests
        import uuid as _uuid
        url = f"{_AG_API_URL}/v1internal:generateContent"
        
        # 清理输入
        project_id = str(project_id).strip()
        model_name = str(self._model_name).strip()
        
        body_dict: dict[str, Any] = {
            "model": model_name,
            "project": project_id,
            "request": payload,
        }
        # 非免费模型需要注入 credits
        if self._needs_credits():
            body_dict["enabledCreditTypes"] = ["GOOGLE_ONE_AI"]

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
            "User-Agent": _AG_USER_AGENT,
            "requestType": "agent",
        }
        
        last_err = None
        for attempt in range(5):
            try:
                # 每次重试生成新的 requestId
                headers["requestId"] = f"req-{_uuid.uuid4()}"
                
                resp = requests.post(
                    url, 
                    json=body_dict, 
                    headers=headers, 
                    timeout=120,
                )
                
                if resp.status_code == 200:
                    return resp.json()
                
                err_body = resp.text
                logger.warning("CodaCloud attempt %d/5 HTTP %d: %s", attempt + 1, resp.status_code, err_body)
                
                if resp.status_code in [401, 403]: # 鉴权错不重试
                    resp.raise_for_status()
                
                resp.raise_for_status()
            except Exception as e:
                logger.warning("CodaCloud attempt %d/5 error: %s", attempt + 1, e)
                last_err = e
                if isinstance(e, requests.exceptions.HTTPError) and e.response.status_code in [401, 403]:
                    break
        
        if last_err:
            raise last_err
        return {} # 兜底

    def _build_payload(
        self,
        messages: Sequence[Mapping[str, object]],
        temperature: float,
    ) -> dict[str, Any]:
        """将标准 messages 格式转为 Coda API 的 Gemini-style payload。"""
        contents: list[dict[str, Any]] = []
        system_instruction: str | None = None

        for msg in messages:
            role = str(msg.get("role", "user"))
            content = msg.get("content", "")

            if role == "system":
                system_instruction = str(content)
                continue

            gemini_role = "model" if role in ("assistant", "model") else "user"
            contents.append({
                "role": gemini_role,
                "parts": [{"text": str(content)}],
            })

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": self._model_max_output_tokens(),
                "temperature": temperature,
            },
        }
        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }
        return payload

    @override
    async def call(
        self,
        messages: Sequence[Mapping[str, object]],
        tools: Sequence[Mapping[str, object]] | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """调用 Coda Cloud API。"""
        access_token, project_id = await _ag_token_cache.ensure_valid()
        payload = self._build_payload(messages, temperature)

        loop = asyncio.get_running_loop()
        for attempt in range(MAX_RETRIES):
            try:
                data = await loop.run_in_executor(
                    None,
                    self._generate_content_sync,
                    access_token,
                    project_id,
                    payload,
                )
                return self._parse_response(data)
            except requests.exceptions.RequestException as e:
                status = getattr(e.response, "status_code", 0) if hasattr(e, "response") else 0
                err_body = getattr(e.response, "text", str(e)) if hasattr(e, "response") else str(e)
                logger.warning(
                    "CodaCloud attempt %d/%d HTTP %d: %s",
                    attempt + 1, MAX_RETRIES, status, err_body[:200],
                )
                if status == 401:
                    # Token 过期 — 强制刷新
                    _ag_token_cache._access_token = ""
                    access_token, project_id = await _ag_token_cache.ensure_valid()
                elif status in (429, 503):
                    delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
                    await asyncio.sleep(delay)
                else:
                    # 对于 404 等错误，如果重试多次都一样，最终抛出
                    if attempt >= MAX_RETRIES - 1:
                        raise RuntimeError(f"Coda API error {status}: {err_body[:300]}")
            except Exception as e:
                logger.warning(
                    "CodaCloud attempt %d/%d: %s", attempt + 1, MAX_RETRIES, e
                )
                if attempt >= MAX_RETRIES - 1:
                    raise
                delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
                await asyncio.sleep(delay)

        raise RuntimeError("CodaCloudCaller: all retries exhausted")

    def _model_max_output_tokens(self) -> int:
        """根据模型动态决定 maxOutputTokens。"""
        name = self._model_name.lower()
        # Gemini 2.5 Pro / Claude Sonnet 大型模型
        if any(k in name for k in ("2.5-pro", "sonnet-4", "claude-4", "opus")):
            return 32768
        # Gemini 2.5 Flash / Claude Sonnet 3.5
        if any(k in name for k in ("2.5-flash", "sonnet", "claude-3-5")):
            return 16384
        # Gemini Flash-Lite / Haiku / 小模型
        return 8192

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        """
        解析 Coda Cloud API 响应。

        实际响应结构 (V1 internal):
          {"response": {"candidates": [...], "usageMetadata": {...}},
           "traceId": "...",
           "consumedCredits": [...],
           "remainingCredits": [...]}
        """
        # 跳到 response 子层级 (服务端将真正的 Gemini 响应嵌套在 response 字段下)
        inner = data.get("response", data)

        text_parts: list[str] = []
        tool_calls: list[dict[str, object]] = []

        for candidate in inner.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                if "text" in part:
                    text_parts.append(part["text"])
                elif "functionCall" in part:
                    fc = part["functionCall"]
                    tool_calls.append({
                        "name": fc.get("name", ""),
                        "arguments": fc.get("args", {}),
                    })

        usage = inner.get("usageMetadata", {})

        # 记录 credit 消耗 (可观测)
        consumed = data.get("consumedCredits", [])
        remaining = data.get("remainingCredits", [])
        if consumed:
            amt = consumed[0].get("creditAmount", "?") if consumed else "?"
            rem = remaining[0].get("creditAmount", "?") if remaining else "?"
            logger.info(
                "CodaCloud credit consumed=%s, remaining=%s", amt, rem
            )

        return LLMResponse(
            text="\n".join(text_parts),
            tool_calls=tool_calls,
            raw=data,
            input_tokens=int(usage.get("promptTokenCount", 0)),
            output_tokens=int(usage.get("candidatesTokenCount", 0)),
            model=inner.get("modelVersion", self._model_name),
        )


# ════════════════════════════════════════════════════════════
#  工厂路由
# ════════════════════════════════════════════════════════════

def create_caller(model: str, api_key: str | None = None) -> BaseLLM:
    """工厂函数，支持多级先后顺序与自动降级。"""
    m = model.lower()
    
    # ── V7.1: 多级先后顺序 (Tiered Priority Chain) ──
    # 从 .env 读取 LLM_PRIORITY_CHAIN，如 "ide,google,ollama"
    priority_chain = os.getenv("LLM_PRIORITY_CHAIN", "ide,google,ollama")
    if priority_chain:
        chain = [p.strip().lower() for p in priority_chain.split(",")]
        logger.info(f"⚡ [Tiered] Multi-level priority active: {chain}")
        return TieredResilientLLM(chain, requested_model=model)

    force_ollama = os.getenv("FORCE_OLLAMA", "false").lower() == "true"
    local_first = os.getenv("LOCAL_FIRST", "false").lower() == "true"

    # ── IDE 内置占位符模型 → CodaCloudCaller ──
    if m.startswith("model_placeholder_"):
        logger.info("Routing IDE placeholder '%s' → CodaCloudCaller", model)
        return CodaCloudCaller(model)

    # 如果强制 Ollama，直接返回
    if force_ollama:
        logger.info("FORCE_OLLAMA active, routing to Ollama")
        return OllamaCaller(model)

    # 构造基础 Caller
    base_caller: BaseLLM
    if "gemini" in m or "google" in m:
        base_caller = GeminiCaller(api_key, model)
    elif "claude" in m or "anthropic" in m:
        base_caller = ClaudeCaller(api_key, model)
    elif "gpt" in m or "openai" in m:
        base_caller = OpenAICaller(api_key, model)
    elif "ollama" in m or "glm" in m:
        base_caller = OllamaCaller(model)
    else:
        base_caller = GeminiCaller(api_key, model)

    # 如果是本地优先，或者开启了自动降级
    if local_first or os.getenv("AUTO_FALLBACK_TO_OLLAMA", "true").lower() == "true":
        return ResilientLLM(base_caller)

    return base_caller


class TieredResilientLLM(BaseLLM):
    """
    [V7.1] 多级自愈模型。
    按照 .env 中 LLM_PRIORITY_CHAIN 定义的顺序逐个尝试。
    """
    def __init__(self, chain: list[str], requested_model: str):
        self.chain = chain
        self.requested_model = requested_model
        self._callers: list[BaseLLM] = []
        
        # 预加载 Caller 链
        for provider in chain:
            if provider == "google" or provider == "gemini":
                # 如果主请求就是 google，保留原始模型名，否则用默认
                m = requested_model if "gemini" in requested_model.lower() else os.getenv("DEFAULT_MODEL_NAME")
                self._callers.append(GeminiCaller(model=m))
            elif provider == "anthropic" or provider == "claude":
                m = requested_model if "claude" in requested_model.lower() else "claude-3-5-sonnet-latest"
                self._callers.append(ClaudeCaller(model=m))
            elif provider == "ollama":
                self._callers.append(OllamaCaller())
            elif provider == "openai":
                m = requested_model if "gpt" in requested_model.lower() else "gpt-4o"
                self._callers.append(OpenAICaller(model=m))
            elif provider == "ide" or provider == "cloud":
                # [V7.1] IDE 内置模型列表 (使用 CodaCloudCaller 透传)
                m = requested_model if requested_model.startswith("model_placeholder") else f"model_placeholder_{requested_model}"
                self._callers.append(CodaCloudCaller(m))

    @property
    def model_name(self) -> str:
        return f"tiered({','.join(self.chain)})"

    async def call(self, messages, tools=None, temperature=0.7) -> LLMResponse:
        last_err = None
        for i, caller in enumerate(self._callers):
            provider = self.chain[i]
            try:
                logger.info(f"🌀 [Tiered] Attempting tier {i+1}: {provider}...")
                res = await caller.call(messages, tools, temperature)
                if i > 0:
                    res.text = f"[FALLBACK:{provider.upper()}] {res.text}"
                return res
            except Exception as e:
                last_err = e
                err_msg = str(e)
                logger.warning(f"⚠️ [Tiered] Tier {provider} failed: {err_msg[:60]}")
                # 如果是业务逻辑错（非 429/Auth），可能不需要切，但为了鲁棒性，通常继续
                continue
        
        raise last_err or RuntimeError("All tiers in priority chain failed")


class ResilientLLM(BaseLLM):
    """具有自愈能力的 LLM 包装器，支持云端故障自动切本地。"""
    
    def __init__(self, primary: BaseLLM):
        self.primary = primary
        self.fallback = OllamaCaller()
        self._model_name = primary.model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    async def call(self, messages, tools=None, temperature=0.7) -> LLMResponse:
        try:
            # 尝试主要模型
            return await self.primary.call(messages, tools, temperature)
        except Exception as e:
            err_msg = str(e)
            # 如果是配额、限流、欠费或鉴权错误，自动切本地
            if any(k in err_msg.lower() for k in ["429", "quota", "limit", "auth", "leaked", "permission"]):
                logger.warning(f"🛡️ [Resilience] Primary LLM failed ({err_msg[:50]}), failing over to Ollama...")
                try:
                    res = await self.fallback.call(messages, tools, temperature)
                    res.text = f"[FALLBACK] {res.text}"
                    return res
                except Exception as fe:
                    logger.error(f"❌ [Resilience] Fallback also failed: {fe}")
                    raise e # 抛出原错
            raise e
