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
from collections.abc import Sequence, Mapping, Callable
from typing import Any, cast, Protocol, runtime_checkable, override, TYPE_CHECKING

from .base_types import (
    BaseLLM,
    LLMResponse,
)

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


class GeminiCaller(BaseLLM):
    """Google Gemini API 调用器。"""

    _model_name: str
    api_key: str
    _client: Any
    _owner_identity: str = "unknown"

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self._model_name = model or os.getenv("DEFAULT_MODEL_NAME", "gemini-2.0-flash")
        self._client = None
        self._owner_identity = os.getenv("Coda_AGENT_IDENTITY", "unknown")

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

        contents: list[types.Content] = []
        system_instruction: str | None = None

        for msg in messages:
            role = str(msg.get("role", "user"))
            content = msg.get("content", "")

            if role == "system":
                system_instruction = str(content)
                continue

            if role in ("model", "assistant"):
                parts: list[types.Part] = [types.Part.from_text(text=str(content))] if isinstance(content, str) else cast("list[types.Part]", content)
                contents.append(types.Content(role="model", parts=parts))
            elif role == "tool":
                tool_results = json.loads(str(content)) if isinstance(content, str) else content
                if isinstance(tool_results, list):
                    tool_parts: list[types.Part] = []
                    for tr in cast("list[dict[str, Any]]", tool_results):
                        tool_parts.append(types.Part.from_function_response(
                            name=str(tr.get("tool_name", "unknown")),
                            response={"result": tr.get("result", "")},
                        ))
                    contents.append(types.Content(role="user", parts=tool_parts))
            else:
                user_parts: list[types.Part] = []
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
            or os.getenv("ANTHROPIC_API_KEY", "")
            or os.getenv("ANTHROPIC_AUTH_TOKEN", "")
        )
        self._model_name = model or os.getenv("DEFAULT_MODEL_NAME", "claude-3-5-sonnet-20241022")
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
                
                self._client = AsyncAnthropic(**kwargs)
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
            "max_tokens": 8192,
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
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self._model_name = model or os.getenv("DEFAULT_MODEL_NAME", "gpt-4o")
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
        m = model or os.getenv("DEFAULT_MODEL_NAME", "glm-4:9b")
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

# Coda IDE 专用 OAuth 凭证 (与 gcli2api 一致)
_AG_CLIENT_ID = "YOUR_CLIENT_ID_HERE"
_AG_CLIENT_SECRET = "YOUR_CLIENT_SECRET_HERE"
_AG_API_URL = "https://daily-cloudcode-pa.googleapis.com"
_AG_USER_AGENT = "Coda/1.22.2 windows/amd64"
_AG_STATE_DB_PATH = os.path.expandvars(
    r"%APPDATA%\Coda\User\globalStorage\state.vscdb"
)

# IDE 占位符 → 真实模型名映射
_PLACEHOLDER_MODEL_MAP: dict[str, str] = {
    "model_placeholder_m35": "claude-sonnet-4-6",
    "model_placeholder_m26": "gemini-2.5-pro",
    "model_placeholder_m37": "gemini-2.5-flash",
    "model_placeholder_m36": "gemini-2.5-flash",
    "model_placeholder_m47": "claude-sonnet-4-6",
}


class _CodaTokenCache:
    """OAuth token cache — 从 IDE state.vscdb 提取 refresh_token 并管理 access_token 生命周期。"""

    def __init__(self) -> None:
        self._access_token: str = ""
        self._expires_at: float = 0.0
        self._project_id: str = ""
        self._refresh_token: str = ""
        self._lock = asyncio.Lock()

    def _extract_refresh_token(self) -> str:
        """从 IDE state.vscdb 的 agentManagerInitState 提取 Google OAuth refresh_token。"""
        if not os.path.exists(_AG_STATE_DB_PATH):
            raise FileNotFoundError(f"IDE state database not found: {_AG_STATE_DB_PATH}")
        conn = sqlite3.connect(_AG_STATE_DB_PATH)
        try:
            row = conn.execute(
                "SELECT value FROM ItemTable WHERE key=?",
                ("jetskiStateSync.agentManagerInitState",),
            ).fetchone()
            if not row:
                raise RuntimeError("agentManagerInitState not found in state.vscdb")
            decoded = base64.b64decode(row[0])
            text = decoded.decode("utf-8", errors="replace")
            tokens = re.findall(r"1//[A-Za-z0-9_\-]{40,}", text)
            if not tokens:
                raise RuntimeError("No refresh_token found in agentManagerInitState")
            return tokens[0]
        finally:
            conn.close()

    def _refresh_access_token_sync(self) -> dict[str, Any]:
        """同步刷新 access_token (在 executor 中运行)。"""
        data = urllib.parse.urlencode({
            "client_id": _AG_CLIENT_ID,
            "client_secret": _AG_CLIENT_SECRET,
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
        payload = json.dumps({"metadata": {"ideType": "Coda"}}).encode()
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {access_token}")
        req.add_header("User-Agent", _AG_USER_AGENT)
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            return json.loads(raw.decode())

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


# 模块级单例
_ag_token_cache = _CodaTokenCache()


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
        "gemini-3.1-flash-lite",
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
        import uuid as _uuid
        url = f"{_AG_API_URL}/v1internal:generateContent"
        body_dict: dict[str, Any] = {
            "model": self._model_name,
            "project": project_id,
            "request": payload,
        }
        # 非免费模型需要注入 credits
        if self._needs_credits():
            body_dict["enabledCreditTypes"] = ["GOOGLE_ONE_AI"]

        body = json.dumps(body_dict).encode()
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {access_token}")
        req.add_header("User-Agent", _AG_USER_AGENT)
        req.add_header("requestType", "agent")
        req.add_header("requestId", f"req-{_uuid.uuid4()}")
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(self._decode_raw(resp.read()))

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
                "maxOutputTokens": 8192,
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
            except urllib.error.HTTPError as e:
                status = e.code
                err_body = self._decode_raw(e.read())
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
                    raise RuntimeError(
                        f"Coda API error {status}: {err_body[:300]}"
                    )
            except Exception as e:
                logger.warning(
                    "CodaCloud attempt %d/%d: %s", attempt + 1, MAX_RETRIES, e
                )
                if attempt >= MAX_RETRIES - 1:
                    raise
                delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
                await asyncio.sleep(delay)

        raise RuntimeError("CodaCloudCaller: all retries exhausted")

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
    """工厂函数。"""
    m = model.lower()

    # 检测是否强制使用 Ollama (通过模型名或环境变量)
    force_ollama = os.getenv("FORCE_OLLAMA", "false").lower() == "true"

    # ── IDE 内置占位符模型 → CodaCloudCaller ──
    if m.startswith("model_placeholder_"):
        logger.info("Routing IDE placeholder '%s' → CodaCloudCaller", model)
        return CodaCloudCaller(model)

    if "gemini" in m and not force_ollama:
        return GeminiCaller(api_key, model)
    if "claude" in m and not force_ollama:
        return ClaudeCaller(api_key, model)
    if "gpt" in m and not force_ollama:
        return OpenAICaller(api_key, model)

    # 如果包含 ollama 或 glm (本地常用) 或强制本地
    if "ollama" in m or "glm" in m or force_ollama:
        return OllamaCaller(model)

    return GeminiCaller(api_key, model)

