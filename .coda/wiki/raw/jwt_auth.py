"""
Coda V4.0 — JWT Authentication (中重要度 #10)
JSON Web Token 签发与验证: 替代简单 HMAC, 实现完整的身份认证。

支持:
  - Token 签发 (sign) 与验证 (verify)
  - 过期时间设定 (exp)
  - 自定义声明 (claims)
  - Agent 身份声明 (sub)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import cast


class JWTError(Exception):
    """JWT 操作异常。"""
    pass


class JWT:
    """
    轻量 JWT 实现 (无外部依赖)。

    使用 HMAC-SHA256 签名, 支持标准 JWT 声明。
    """

    def __init__(self, secret: str):
        self._secret: bytes = secret.encode("utf-8")

    def sign(
        self, subject: str, claims: dict[str, object] | None = None, expires_in: int = 3600
    ) -> str:
        """
        签发 JWT Token。

        Args:
            subject: 主体 (通常是 agent_id)
            claims: 自定义声明
            expires_in: 过期时间 (秒)
        """
        now = int(time.time())
        header = {"alg": "HS256", "typ": "JWT"}
        payload: dict[str, object] = {
            "sub": subject,
            "iat": now,
            "exp": now + expires_in,
            **(claims or {}),
        }

        h = self._b64encode(json.dumps(header))
        p = self._b64encode(json.dumps(payload))
        signature = self._hmac_sign(f"{h}.{p}")
        return f"{h}.{p}.{signature}"

    def verify(self, token: str) -> dict[str, object]:
        """
        验证 JWT Token, 返回 payload。

        Raises:
            JWTError: 签名无效或 Token 已过期
        """
        parts = token.split(".")
        if len(parts) != 3:
            raise JWTError("Invalid token format")

        h, p, sig = parts

        # 验证签名
        expected_sig = self._hmac_sign(f"{h}.{p}")
        if not hmac.compare_digest(sig, expected_sig):
            raise JWTError("Invalid signature")

        # 解码 payload
        try:
            payload = json.loads(self._b64decode(p))
            if not isinstance(payload, dict):
                raise JWTError("Invalid payload type")
            payload_dict: dict[str, object] = cast(dict[str, object], payload)
        except Exception:
            raise JWTError("Invalid payload encoding")

        # 检查过期
        exp_obj = payload_dict.get("exp", 0)
        exp = int(float(exp_obj)) if isinstance(exp_obj, (int, float, str)) else 0
        if exp and time.time() > exp:
            raise JWTError(f"Token expired at {exp}")

        return payload_dict

    def refresh(self, token: str, expires_in: int = 3600) -> str:
        """刷新 Token (延长过期时间)。"""
        payload = self.verify(token)  # 验证旧 Token
        sub = str(payload.get("sub", ""))
        claims: dict[str, object] = {str(k): v for k, v in payload.items() if k not in ("sub", "iat", "exp")}
        return self.sign(
            subject=sub,
            claims=claims,
            expires_in=expires_in,
        )

    def _hmac_sign(self, data: str) -> str:
        """HMAC-SHA256 签名。"""
        sig = hmac.new(self._secret, data.encode("utf-8"), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(sig).rstrip(b"=").decode("utf-8")

    def _b64encode(self, data: str) -> str:
        return base64.urlsafe_b64encode(data.encode("utf-8")).rstrip(b"=").decode("utf-8")

    def _b64decode(self, data: str) -> str:
        # 补齐 padding
        padding = 4 - len(data) % 4
        if padding != 4:
            data += "=" * padding
        return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8")
