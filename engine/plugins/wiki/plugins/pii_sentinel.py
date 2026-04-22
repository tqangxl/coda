"""
Coda Knowledge Engine V6.0 — PII Sentinel (隐私海关)
本地 PII 检测与脱敏: 数据进入 LLM 前的最后防线。

实现:
  - 多策略 PII 检测 (正则 + presidio 抽象层)
  - 可逆脱敏 (保留结构, 替换值)
  - 风险分级 (HIGH/MEDIUM/LOW)
  - 审计日志集成
  - .Coda_no_llm 文件级标记
"""

from __future__ import annotations

from ..base_plugin import WikiPlugin, WikiHook, WikiPluginContext

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("Coda.wiki.pii")


# ════════════════════════════════════════════
#  PII 检测正则 (本地无依赖)
# ════════════════════════════════════════════

PII_PATTERNS: dict[str, dict[str, Any]] = {
    "email": {
        "pattern": re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
        "risk": "MEDIUM",
        "replacement": "[EMAIL_REDACTED]",
    },
    "phone_cn": {
        "pattern": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
        "risk": "HIGH",
        "replacement": "[PHONE_REDACTED]",
    },
    "phone_intl": {
        "pattern": re.compile(r"\+?\d{1,4}[\s-]?\(?\d{1,4}\)?[\s-]?\d{3,4}[\s-]?\d{3,4}"),
        "risk": "HIGH",
        "replacement": "[PHONE_REDACTED]",
    },
    "id_card_cn": {
        "pattern": re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
        "risk": "HIGH",
        "replacement": "[ID_REDACTED]",
    },
    "credit_card": {
        "pattern": re.compile(r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)"),
        "risk": "HIGH",
        "replacement": "[CARD_REDACTED]",
    },
    "ssn_us": {
        "pattern": re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"),
        "risk": "HIGH",
        "replacement": "[SSN_REDACTED]",
    },
    "ip_address": {
        "pattern": re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
        "risk": "LOW",
        "replacement": "[IP_REDACTED]",
    },
    "api_key_openai": {
        "pattern": re.compile(r"sk-[a-zA-Z0-9]{20,}"),
        "risk": "HIGH",
        "replacement": "[API_KEY_REDACTED]",
    },
    "api_key_google": {
        "pattern": re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
        "risk": "HIGH",
        "replacement": "[API_KEY_REDACTED]",
    },
    "password_in_url": {
        "pattern": re.compile(r"(?i)(?:password|passwd|pwd)\s*[=:]\s*\S+"),
        "risk": "HIGH",
        "replacement": "[PASSWORD_REDACTED]",
    },
    "aws_key": {
        "pattern": re.compile(r"AKIA[0-9A-Z]{16}"),
        "risk": "HIGH",
        "replacement": "[AWS_KEY_REDACTED]",
    },
    "private_key": {
        "pattern": re.compile(r"-----BEGIN (?:RSA |DSA |EC )?PRIVATE KEY-----"),
        "risk": "HIGH",
        "replacement": "[PRIVATE_KEY_REDACTED]",
    },
}


@dataclass
class PIIDetection:
    """单个 PII 检测结果。"""
    pii_type: str
    value: str
    risk: str  # HIGH / MEDIUM / LOW
    start: int
    end: int
    replacement: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "pii_type": self.pii_type,
            "value": self.value,
            "risk": self.risk,
            "start": self.start,
            "end": self.end,
            "replacement": self.replacement,
        }

    @property
    def is_high_risk(self) -> bool:
        return self.risk == "HIGH"


@dataclass
class SanitizationResult:
    """脱敏结果。"""
    original_text: str
    sanitized_text: str
    detections: list[PIIDetection] = field(default_factory=list)
    risk_score: float = 0.0
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_text": self.original_text,
            "sanitized_text": self.sanitized_text,
            "detections": [d.to_dict() for d in self.detections],
            "risk_score": self.risk_score,
            "elapsed_ms": self.elapsed_ms,
            "has_pii": self.has_pii,
            "high_risk_count": self.high_risk_count,
        }

    @property
    def has_pii(self) -> bool:
        return len(self.detections) > 0

    @property
    def high_risk_count(self) -> int:
        return sum(1 for d in self.detections if d.is_high_risk)

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "pii_count": len(self.detections),
            "high_risk_count": self.high_risk_count,
            "risk_score": self.risk_score,
            "types_found": list(set(d.pii_type for d in self.detections)),
            "elapsed_ms": self.elapsed_ms,
        }


class PIISentinel(WikiPlugin):
    """
    隐私海关 (Data Customs): 所有数据进入 LLM 前的必经关卡。
    """
    name = "pii"

    def __init__(self, mode: str = "SANITIZE"):
        """
        Args:
            mode: 工作模式 - DETECT / SANITIZE / BLOCK
        """
        if mode not in ("DETECT", "SANITIZE", "BLOCK"):
            raise ValueError(f"Invalid PII mode: {mode}. Must be DETECT/SANITIZE/BLOCK.")
        self._mode = mode
        self._presidio_available = False
        self._analyzer: Any = None
        self._init_presidio()

    async def initialize(self, ctx: WikiPluginContext) -> None:
        """插件初始化入口。"""
        logger.info(f"🛡️ PII Sentinel initialized (mode={self._mode})")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        """响应 Wiki 钩子。"""
        return None

    def _init_presidio(self) -> None:
        """尝试加载 presidio-analyzer (可选增强)。"""
        try:
            from presidio_analyzer import AnalyzerEngine  # pyright: ignore[reportMissingImports]
            self._analyzer = AnalyzerEngine()
            self._presidio_available = True
            logger.info("✅ Presidio analyzer loaded for enhanced PII detection")
        except ImportError:
            logger.info("ℹ️ Presidio not available, using regex-only PII detection")

    def scan(self, text: str) -> SanitizationResult:
        """
        扫描文本中的 PII。
        根据模式执行检测/脱敏/拦截。
        """
        start_time = time.time()
        detections: list[PIIDetection] = []

        # ── 正则检测 ──
        for pii_type, config in PII_PATTERNS.items():
            pattern = config["pattern"]
            for match in pattern.finditer(text):
                detections.append(PIIDetection(
                    pii_type=pii_type,
                    value=match.group(),
                    risk=config["risk"],
                    start=match.start(),
                    end=match.end(),
                    replacement=config["replacement"],
                ))

        # ── Presidio 增强检测 ──
        if self._presidio_available and self._analyzer:
            try:
                results = self._analyzer.analyze(text=text, language="en", score_threshold=0.7)
                for result in results:
                    pii_type = result.entity_type.lower()
                    if not any(d.start == result.start and d.end == result.end for d in detections):
                        detections.append(PIIDetection(
                            pii_type=f"presidio_{pii_type}",
                            value=text[result.start:result.end],
                            risk="HIGH" if result.score > 0.85 else "MEDIUM",
                            start=result.start,
                            end=result.end,
                            replacement=f"[{pii_type.upper()}_REDACTED]",
                        ))
            except Exception as e:
                logger.warning(f"Presidio scan failed: {e}")

        # ── 去重 (按位置) ──
        detections = self._deduplicate(detections)

        # ── 计算风险分数 ──
        risk_score = self._compute_risk_score(detections)

        # ── 脱敏处理 ──
        sanitized = text
        if self._mode == "SANITIZE" and detections:
            sanitized = self._apply_sanitization(text, detections)
        elif self._mode == "BLOCK" and any(d.is_high_risk for d in detections):
            raise PermissionError(
                f"PII BLOCK: Found {len(detections)} PII instances "
                f"({sum(1 for d in detections if d.is_high_risk)} high-risk). "
                f"Content blocked from LLM processing."
            )

        elapsed = (time.time() - start_time) * 1000

        return SanitizationResult(
            original_text=text,
            sanitized_text=sanitized,
            detections=detections,
            risk_score=risk_score,
            elapsed_ms=elapsed,
        )

    def scan_file(self, filepath: str | Path) -> SanitizationResult:
        """扫描文件中的 PII。"""
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        # 检查文件级标记
        no_llm_marker = path.parent / ".Coda_no_llm"
        if no_llm_marker.exists():
            logger.warning(f"🔒 File marked .Coda_no_llm: {path}")
            return SanitizationResult(
                original_text="",
                sanitized_text="",
                detections=[PIIDetection(
                    pii_type="file_blocked",
                    value=str(path),
                    risk="HIGH",
                    start=0, end=0,
                    replacement="[FILE_BLOCKED]",
                )],
                risk_score=10.0,
            )

        content = path.read_text(encoding="utf-8", errors="replace")
        return self.scan(content)

    def sanitize_for_llm(self, text: str) -> str:
        """
        LLM 调用前的快速脱敏。
        返回脱敏后的文本 (适合作为 compiler 与 LLM 之间的中间件)。
        """
        result = self.scan(text)
        return result.sanitized_text

    def _apply_sanitization(self, text: str, detections: list[PIIDetection]) -> str:
        """应用脱敏替换 (从后往前, 避免偏移)。"""
        # 按位置从后到前排序
        sorted_detections = sorted(detections, key=lambda d: d.start, reverse=True)
        result = text
        for det in sorted_detections:
            result = result[:det.start] + det.replacement + result[det.end:]
        return result

    def _deduplicate(self, detections: list[PIIDetection]) -> list[PIIDetection]:
        """去重: 优先保留高风险检测。"""
        unique: list[PIIDetection] = []
        seen_ranges: set[tuple[int, int]] = set()

        # 按风险等级排序 (HIGH > MEDIUM > LOW)
        risk_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        sorted_dets = sorted(detections, key=lambda d: risk_order.get(d.risk, 3))

        for det in sorted_dets:
            overlap = False
            for start, end in seen_ranges:
                if det.start < end and det.end > start:
                    overlap = True
                    break
            if not overlap:
                unique.append(det)
                seen_ranges.add((det.start, det.end))

        return unique

    def _compute_risk_score(self, detections: list[PIIDetection]) -> float:
        """计算整体风险分数 (0-10)。"""
        if not detections:
            return 0.0

        risk_weights = {"HIGH": 3.0, "MEDIUM": 1.5, "LOW": 0.5}
        total = sum(risk_weights.get(d.risk, 0.5) for d in detections)
        return min(10.0, total)
