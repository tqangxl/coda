"""
Coda V6.1 — Universal Advisor Engine (军师引擎)
超越 Anthropic Cloud 的通用 Advisor-Executor 系统。

核心差异化:
  - 全球 Top 20 模型供应商任意搭配
  - 4 种策略: Solo / Council / Debate / Cascade
  - Elo 评分驱动的反馈闭环
  - 按领域自动路由 (代码→DeepSeek R1, 推理→o3, 创意→Claude)
  - 动态预算感知路由
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Sequence, Mapping

from .base_types import BaseLLM, LLMResponse, UniversalCognitivePacket, SovereignIdentity

logger = logging.getLogger("Coda.advisor")


# ════════════════════════════════════════════
#  模型身份证 (Model Card)
# ════════════════════════════════════════════

class ModelTier(str, Enum):
    """模型级别。"""
    FLAGSHIP = "flagship"      # 旗舰 (最强推理)
    WORKHORSE = "workhorse"    # 主力 (性价比)
    SPEED = "speed"            # 极速 (低延迟)
    LOCAL = "local"            # 本地 (离线)


class ModelSpecialty(str, Enum):
    """模型专长领域。"""
    REASONING = "reasoning"
    CODE = "code"
    CREATIVE = "creative"
    MATH = "math"
    MULTILINGUAL = "multilingual"
    LONG_CONTEXT = "long_context"
    TOOL_USE = "tool_use"
    VISION = "vision"
    GENERAL = "general"


@dataclass
class ModelCard:
    """
    模型身份证 — 描述一个 AI 模型的全部元数据。

    用于路由决策:
    - tier: 决定是否适合做军师 (flagship) 或特种兵 (workhorse/speed)
    - specialties: 按领域匹配最佳军师
    - cost: 成本优化
    - elo_rating: 历史表现
    """
    model_id: str               # "claude-opus-4-20250514"
    provider: str               # "anthropic"
    display_name: str           # "Claude Opus 4"
    tier: ModelTier = ModelTier.WORKHORSE
    specialties: list[str] = field(default_factory=lambda: ["general"])
    cost_per_mtok_in: float = 3.0   # 输入每百万 token 成本 (USD)
    cost_per_mtok_out: float = 15.0  # 输出每百万 token 成本 (USD)
    context_window: int = 200000     # 最大上下文窗口
    latency_class: str = "medium"    # "fast" / "medium" / "slow"

    # ── Elo 评分系统 ──
    elo_advisor: float = 1500.0      # 作为军师的 Elo 评分
    elo_executor: float = 1500.0     # 作为特种兵的 Elo 评分
    advisor_matches: int = 0         # 军师场次
    executor_matches: int = 0        # 特种兵场次
    advisor_wins: int = 0
    executor_wins: int = 0

    # ── V6.5: 效能画像 (Performance/Efficiency) ──
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_spent: float = 0.0
    advisor_success_count: int = 0
    executor_success_count: int = 0

    # ── 可用性 ──
    api_key_env: str = ""            # 环境变量名 (如 "ANTHROPIC_API_KEY")
    base_url_env: str = ""           # base_url 环境变量名 (OpenAI 兼容)
    openai_compatible: bool = False  # 是否兼容 OpenAI 协议
    specific_tier: str = ""          # 细分级别 (如 "high", "low", "thinking")

    @property
    def is_available(self) -> bool:
        """
        检查模型是否可用。

        优先级:
        1. 显式 API Key (标准外部调用)
        2. IDE 环境 (Coda_AGENT=1): 根据 IDE Bridge 实时配额检查
        3. Google ADC 探针
        """
        # 1. 标准 API Key 检查
        if self.api_key_env and os.getenv(self.api_key_env, ""):
            return True

        # 2. Coda IDE 环境 + IDE Bridge 实时配额
        if os.getenv("Coda_AGENT") == "1":
            # 如果是 IDE 专属模型 (以 MODEL_ 开头) 或者 Anthropic 模型
            if self.model_id.startswith("MODEL_") or self.provider == "anthropic":
                # 尝试导入 IDEBridge 进行实时配额检查
                try:
                    from .ide_bridge import IDEBridge
                    # 注意: ide_bridge 是单例，且通常是异步连接的。
                    # 如果尚未连接，这里只能基于静态条件返回 True。
                    # 如果已连接，则检查配额
                    bridge = IDEBridge._instance
                    if bridge and bridge.is_connected:
                        return bridge.is_model_available(self.model_id)
                    
                    # 后备逻辑：如果 bridge 未初始化，但我们确信身处 IDE，
                    # 则允许路由，等执行时再抛出配额耗尽异常
                    return True
                except ImportError:
                    return True
            return False

        # 3. 提供商特定深度探针 (仅当不在 IDE 环境下且未提供 API Key 时尝试)
        if self.provider == "google":
            try:
                # ── V6.5: 环境隔离优化 ──
                # 使用 importlib 动态加载以消除 IDE 中“找不到模块”的红线警告
                import importlib
                auth = importlib.import_module("google.auth")
                auth_exceptions = importlib.import_module("google.auth.exceptions")
                DefaultCredentialsError = auth_exceptions.DefaultCredentialsError
                
                try:
                    _, _ = auth.default()
                    return True
                except (DefaultCredentialsError, Exception):
                    return os.getenv("Coda_IDE_GOOGLE_AUTH") == "true"
            except (ImportError, ModuleNotFoundError):
                # 如果没装库，但环境变量提示可用 (比如通过 IDE 代理)，则允许
                return os.getenv("Coda_IDE_GOOGLE_AUTH") == "true" or os.getenv("Coda_AGENT") == "1"

        return False

    @property
    def advisor_win_rate(self) -> float:
        return self.advisor_wins / max(self.advisor_matches, 1)

    @property
    def executor_win_rate(self) -> float:
        return self.executor_wins / max(self.executor_matches, 1)

    @property
    def cost_score(self) -> float:
        """成本得分 (越低越便宜)。"""
        return (self.cost_per_mtok_in + self.cost_per_mtok_out) / 2

    @property
    def efficiency_index(self) -> float:
        """
        效能指数 (越高越好)。
        公式: (成功场次 / 总场次) / (平均单位成本 + 1e-6)
        """
        total_matches = self.advisor_matches + self.executor_matches
        total_success = self.advisor_success_count + self.executor_success_count
        if total_matches == 0:
            return 1.0  # 初始中值
        
        success_rate = total_success / total_matches
        avg_cost = self.total_cost_spent / (total_matches + 1e-6)
        return success_rate / (avg_cost + 1e-6)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["tier"] = self.tier.value
        d["efficiency_index"] = self.efficiency_index
        return d


# ════════════════════════════════════════════
#  策略枚举
# ════════════════════════════════════════════

class AdvisorStrategy(str, Enum):
    """军师策略。"""
    SOLO = "solo"          # 单军师 (类似 Anthropic)
    COUNCIL = "council"    # 多军师投票 (3-5 位并行审议)
    DEBATE = "debate"      # 对抗辩论 (正方 vs 反方)
    CASCADE = "cascade"    # 级联 (便宜先审, 不确定则升级)


# ════════════════════════════════════════════
#  军师裁决
# ════════════════════════════════════════════

@dataclass
class AdvisorOpinion:
    """单个军师的意见。"""
    model_id: str
    provider: str
    verdict: str            # "approve" / "refine" / "abort" / "escalate"
    reasoning: str
    confidence: float = 0.9
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    suggested_refinement: str = ""


@dataclass
class AdvisorVerdict:
    """
    军师裁决 — 聚合多个军师意见后的最终决策。

    比 Anthropic 更高级:
    - 支持多军师投票
    - 记录反对意见
    - 推荐最佳执行者
    - 追踪真实成本
    """
    verdict: str              # "approve" / "refine" / "abort" / "escalate"
    reasoning: str
    confidence: float = 0.9
    strategy_used: AdvisorStrategy = AdvisorStrategy.SOLO
    cost_usd: float = 0.0
    total_latency_ms: float = 0.0

    # ── 多军师信息 ──
    opinions: list[AdvisorOpinion] = field(default_factory=list)
    dissenting_opinions: list[AdvisorOpinion] = field(default_factory=list)
    vote_tally: dict[str, int] = field(default_factory=dict)

    # ── 执行建议 ──
    suggested_executor: str = ""
    suggested_refinement: str = ""

    # ── 追踪 ──
    pairing_id: str = ""
    timestamp: float = field(default_factory=time.time)

    # ── [V6.5] 主权认知包 (用于跨 Agent/IDE 追踪) ──
    handover_pkt: UniversalCognitivePacket | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "strategy": self.strategy_used.value,
            "cost_usd": self.cost_usd,
            "opinions_count": len(self.opinions),
            "dissent_count": len(self.dissenting_opinions),
            "vote_tally": self.vote_tally,
            "suggested_executor": self.suggested_executor,
        }


# ════════════════════════════════════════════
#  全球 Top 20 模型注册表
# ════════════════════════════════════════════

def _build_default_registry() -> list[ModelCard]:
    """构建 2026 全球顶级旗舰模型注册表 (Top 20 Vendors)。"""
    return [
        # 0. Coda IDE Built-in Models
        ModelCard(
            model_id="MODEL_PLACEHOLDER_M35", provider="anthropic",
            display_name="Claude Sonnet 4.6 (IDE)", tier=ModelTier.FLAGSHIP,
            specialties=["reasoning", "code", "creative"],
            cost_per_mtok_in=0.0, cost_per_mtok_out=0.0,  # IDE 内置套餐
            context_window=200000, latency_class="medium",
            api_key_env="ANTHROPIC_AUTH_TOKEN",
        ),
        ModelCard(
            model_id="MODEL_PLACEHOLDER_M26", provider="anthropic",
            display_name="Claude Opus 4.6 (IDE)", tier=ModelTier.FLAGSHIP,
            specialties=["reasoning", "math", "logical"],
            cost_per_mtok_in=0.0, cost_per_mtok_out=0.0,  # IDE 内置套餐
            context_window=200000, latency_class="slow",
            api_key_env="ANTHROPIC_AUTH_TOKEN",
        ),
        ModelCard(
            model_id="MODEL_OPENAI_GPT_OSS_120B_MEDIUM", provider="openai",
            display_name="GPT-OSS 120B (IDE)", tier=ModelTier.WORKHORSE,
            specialties=["code", "general"],
            cost_per_mtok_in=0.0, cost_per_mtok_out=0.0,
            context_window=128000, latency_class="medium",
            api_key_env="ANTHROPIC_AUTH_TOKEN",
            openai_compatible=True,
        ),
        ModelCard(
            model_id="MODEL_PLACEHOLDER_M37", provider="google",
            display_name="Gemini 3.1 Pro High (IDE)", tier=ModelTier.FLAGSHIP,
            specialties=["reasoning", "code", "long_context"],
            cost_per_mtok_in=0.0, cost_per_mtok_out=0.0,
            context_window=2000000, latency_class="medium",
            api_key_env="ANTHROPIC_AUTH_TOKEN", # 实际上被 IDE proxy 劫持，使用此 token 作为认证通过
        ),
        ModelCard(
            model_id="MODEL_PLACEHOLDER_M36", provider="google",
            display_name="Gemini 3.1 Pro Low (IDE)", tier=ModelTier.WORKHORSE,
            specialties=["code", "general"],
            cost_per_mtok_in=0.0, cost_per_mtok_out=0.0,
            context_window=1048576, latency_class="fast",
            api_key_env="ANTHROPIC_AUTH_TOKEN",
        ),
        ModelCard(
            model_id="MODEL_PLACEHOLDER_M47", provider="google",
            display_name="Gemini 3 Flash (IDE)", tier=ModelTier.SPEED,
            specialties=["general", "vision", "fast"],
            cost_per_mtok_in=0.0, cost_per_mtok_out=0.0,
            context_window=1048576, latency_class="fast",
            api_key_env="ANTHROPIC_AUTH_TOKEN",
        ),

        # 1. Anthropic
        ModelCard(
            model_id="claude-opus-4-6-thinking", provider="anthropic",
            display_name="Claude Opus 4.6 (Thinking)", tier=ModelTier.FLAGSHIP,
            specific_tier="thinking",
            specialties=["reasoning", "code", "creative", "long_context"],
            cost_per_mtok_in=12.0, cost_per_mtok_out=60.0,
            context_window=500000, latency_class="slow",
            api_key_env="ANTHROPIC_API_KEY",
        ),
        ModelCard(
            model_id="claude-sonnet-4-6-thinking", provider="anthropic",
            display_name="Claude Sonnet 4.6 (Thinking)", tier=ModelTier.WORKHORSE,
            specific_tier="thinking",
            specialties=["code", "reasoning", "tool_use"],
            cost_per_mtok_in=3.0, cost_per_mtok_out=15.0,
            context_window=200000, latency_class="medium",
            api_key_env="ANTHROPIC_API_KEY",
        ),
        ModelCard(
            model_id="claude-sonnet-4-6", provider="anthropic",
            display_name="Claude Sonnet 4.6", tier=ModelTier.WORKHORSE,
            specific_tier="standard",
            specialties=["code", "general"],
            cost_per_mtok_in=3.0, cost_per_mtok_out=15.0,
            context_window=200000, latency_class="medium",
            api_key_env="ANTHROPIC_API_KEY",
        ),

        # 2. OpenAI
        ModelCard(
            model_id="o4-reasoning-2026-01", provider="openai",
            display_name="o4-reasoning", tier=ModelTier.FLAGSHIP,
            specialties=["reasoning", "math", "code", "logic"],
            cost_per_mtok_in=10.0, cost_per_mtok_out=40.0,
            context_window=200000, latency_class="slow",
            api_key_env="OPENAI_API_KEY",
        ),
        ModelCard(
            model_id="gpt-4.1-2025-04-14", provider="openai",
            display_name="GPT-4.1", tier=ModelTier.WORKHORSE,
            specialties=["code", "general", "tool_use"],
            cost_per_mtok_in=2.0, cost_per_mtok_out=8.0,
            context_window=1048576, latency_class="medium",
            api_key_env="OPENAI_API_KEY",
        ),

        # 3. Google (2026 Fleet)
        ModelCard(
            model_id="gemini-3.1-pro-high", provider="google",
            display_name="Gemini 3.1 Pro (High)", tier=ModelTier.FLAGSHIP,
            specific_tier="high",
            specialties=["reasoning", "code", "long_context", "multimodal"],
            cost_per_mtok_in=1.25, cost_per_mtok_out=10.0,
            context_window=2000000, latency_class="medium",
            api_key_env="GEMINI_API_KEY",
        ),
        ModelCard(
            model_id="gemini-3.1-pro-low", provider="google",
            display_name="Gemini 3.1 Pro (Low)", tier=ModelTier.WORKHORSE,
            specific_tier="low",
            specialties=["code", "general", "long_context"],
            cost_per_mtok_in=0.5, cost_per_mtok_out=2.0,
            context_window=1048576, latency_class="fast",
            api_key_env="GEMINI_API_KEY",
        ),
        ModelCard(
            model_id="gemini-3.1-flash-image", provider="google",
            display_name="Gemini 3.1 Flash Image", tier=ModelTier.SPEED,
            specific_tier="image",
            specialties=["vision", "general"],
            cost_per_mtok_in=0.1, cost_per_mtok_out=0.4,
            context_window=1048576, latency_class="fast",
            api_key_env="GEMINI_API_KEY",
        ),
        ModelCard(
            model_id="gemini-3-flash-2026", provider="google",
            display_name="Gemini 3 Flash", tier=ModelTier.SPEED,
            specialties=["general", "vision", "fast"],
            cost_per_mtok_in=0.1, cost_per_mtok_out=0.4,
            context_window=1048576, latency_class="fast",
            api_key_env="GEMINI_API_KEY",
        ),

        # 4. DeepSeek
        ModelCard(
            model_id="deepseek-r2-reasoning", provider="deepseek",
            display_name="DeepSeek R2", tier=ModelTier.FLAGSHIP,
            specialties=["reasoning", "math", "code"],
            cost_per_mtok_in=0.45, cost_per_mtok_out=1.80,
            context_window=128000, latency_class="slow",
            api_key_env="DEEPSEEK_API_KEY",
            openai_compatible=True,
        ),

        # 5. Mistral
        ModelCard(
            model_id="mistral-small-4-unified", provider="mistral",
            display_name="Mistral Small 4", tier=ModelTier.WORKHORSE,
            specialties=["reasoning", "code", "multimodal"],
            cost_per_mtok_in=0.6, cost_per_mtok_out=2.4,
            context_window=256000, latency_class="medium",
            api_key_env="MISTRAL_API_KEY",
            openai_compatible=True,
        ),

        # 6. Meta
        ModelCard(
            model_id="llama-4-maverick-17b", provider="meta",
            display_name="Llama 4 Maverick (17B)", tier=ModelTier.WORKHORSE,
            specialties=["general", "code", "fast"],
            cost_per_mtok_in=0.2, cost_per_mtok_out=0.6,
            context_window=128000, latency_class="fast",
            api_key_env="TOGETHER_API_KEY",
            openai_compatible=True,
        ),

        # 7. xAI
        ModelCard(
            model_id="grok-3-ultra", provider="xai",
            display_name="Grok 3 Ultra", tier=ModelTier.FLAGSHIP,
            specialties=["reasoning", "code", "creative"],
            cost_per_mtok_in=3.0, cost_per_mtok_out=15.0,
            context_window=131072, latency_class="medium",
            api_key_env="XAI_API_KEY",
            openai_compatible=True,
        ),

        # 8. Alibaba (Qwen)
        ModelCard(
            model_id="qwen-3-ultra-235b", provider="alibaba",
            display_name="Qwen 3 Ultra", tier=ModelTier.FLAGSHIP,
            specialties=["reasoning", "code", "multilingual"],
            cost_per_mtok_in=3.0, cost_per_mtok_out=12.0,
            context_window=131072, latency_class="medium",
            api_key_env="QWEN_API_KEY",
            openai_compatible=True,
        ),

        # 9. MiniMax
        ModelCard(
            model_id="minimax-m2.7-agentic", provider="minimax",
            display_name="MiniMax M2.7 (Agentic)", tier=ModelTier.FLAGSHIP,
            specialties=["agent", "code", "optimization"],
            cost_per_mtok_in=2.0, cost_per_mtok_out=10.0,
            context_window=205000, latency_class="medium",
            api_key_env="MINIMAX_API_KEY",
            openai_compatible=True,
        ),

        # 10. StepFun
        ModelCard(
            model_id="step-3.5-flash", provider="stepfun",
            display_name="Step 3.5 Flash", tier=ModelTier.SPEED,
            specialties=["reasoning", "code", "fast"],
            cost_per_mtok_in=0.1, cost_per_mtok_out=0.4,
            context_window=128000, latency_class="fast",
            api_key_env="STEPFUN_API_KEY",
            openai_compatible=True,
        ),

        # 11. Tencent (Hunyuan)
        ModelCard(
            model_id="hunyuan-3.0-turbo", provider="tencent",
            display_name="Hunyuan 3.0 Turbo", tier=ModelTier.WORKHORSE,
            specialties=["general", "long_context", "agent"],
            cost_per_mtok_in=1.0, cost_per_mtok_out=4.0,
            context_window=128000, latency_class="medium",
            api_key_env="HUNYUAN_API_KEY",
            openai_compatible=True,
        ),

        # 12. 01.AI (Yi)
        ModelCard(
            model_id="yi-lightning-v2", provider="01ai",
            display_name="Yi-Lightning V2", tier=ModelTier.WORKHORSE,
            specialties=["reasoning", "multilingual"],
            cost_per_mtok_in=0.5, cost_per_mtok_out=2.0,
            context_window=128000, latency_class="medium",
            api_key_env="YI_API_KEY",
            openai_compatible=True,
        ),

        # 13. Bytedance (Doubao)
        ModelCard(
            model_id="doubao-pro-256k", provider="bytedance",
            display_name="Doubao Pro (256K)", tier=ModelTier.WORKHORSE,
            specialties=["long_context", "general"],
            cost_per_mtok_in=0.8, cost_per_mtok_out=2.0,
            context_window=256000, latency_class="medium",
            api_key_env="DOUBAO_API_KEY",
            openai_compatible=True,
        ),

        # 14. Baidu (Ernie)
        ModelCard(
            model_id="ernie-4.5-turbo-vl", provider="baidu",
            display_name="Ernie 4.5 Turbo VL", tier=ModelTier.WORKHORSE,
            specialties=["multimodal", "general"],
            cost_per_mtok_in=2.0, cost_per_mtok_out=8.0,
            context_window=32000, latency_class="medium",
            api_key_env="ERNIE_API_KEY",
            openai_compatible=True,
        ),

        # 15. Zhipu (GLM)
        ModelCard(
            model_id="glm-4-plus", provider="zhipu",
            display_name="GLM-4-Plus", tier=ModelTier.WORKHORSE,
            specialties=["reasoning", "code"],
            cost_per_mtok_in=1.0, cost_per_mtok_out=4.0,
            context_window=128000, latency_class="medium",
            api_key_env="GLM_API_KEY",
            openai_compatible=True,
        ),

        # 16. Moonshot (Kimi)
        ModelCard(
            model_id="kimi-k2", provider="moonshot",
            display_name="Kimi K2", tier=ModelTier.WORKHORSE,
            specialties=["long_context", "reasoning"],
            cost_per_mtok_in=2.0, cost_per_mtok_out=8.0,
            context_window=200000, latency_class="medium",
            api_key_env="KIMI_API_KEY",
            openai_compatible=True,
        ),

        # 17. Cohere
        ModelCard(
            model_id="command-r-plus-2026", provider="cohere",
            display_name="Command R+ (2026)", tier=ModelTier.WORKHORSE,
            specialties=["tool_use", "rag", "code"],
            cost_per_mtok_in=2.5, cost_per_mtok_out=10.0,
            context_window=128000, latency_class="medium",
            api_key_env="COHERE_API_KEY",
        ),

        # 18. Amazon
        ModelCard(
            model_id="amazon-nova-pro-v1", provider="amazon",
            display_name="Amazon Nova Pro", tier=ModelTier.WORKHORSE,
            specialties=["multimodal", "general"],
            cost_per_mtok_in=0.8, cost_per_mtok_out=3.2,
            context_window=128000, latency_class="medium",
            api_key_env="AWS_API_KEY",
        ),

        # 19. Reka
        ModelCard(
            model_id="reka-core-2026", provider="reka",
            display_name="Reka Core (2026)", tier=ModelTier.FLAGSHIP,
            specialties=["multimodal", "reasoning"],
            cost_per_mtok_in=3.0, cost_per_mtok_out=15.0,
            context_window=128000, latency_class="medium",
            api_key_env="REKA_API_KEY",
            openai_compatible=True,
        ),

        # 20. OSS / Groq specialized
        ModelCard(
            model_id="gpt-oss-120b-medium", provider="oss",
            display_name="GPT-OSS 120B (Medium)", tier=ModelTier.WORKHORSE,
            specialties=["code", "creative", "multilingual"],
            cost_per_mtok_in=0.1, cost_per_mtok_out=0.3,
            context_window=128000, latency_class="medium",
            api_key_env="GROQ_API_KEY",
            openai_compatible=True,
        ),
    ]


class ModelRegistry:
    """
    全球模型注册表。

    职责:
    1. 维护 Top 20 模型供应商的元数据
    2. 运行时根据 API Key 动态筛选可用模型
    3. 按 tier/specialty/cost 进行模型查询
    4. 持久化 Elo 评分
    """

    def __init__(self, elo_path: str | Path | None = None, db: Any | None = None):
        self._models: dict[str, ModelCard] = {}
        self._elo_path = Path(elo_path) if elo_path else None
        self._db = db

        # 注册默认模型
        for card in _build_default_registry():
            self._models[card.model_id] = card

        # 加载历史 Elo
        if self._elo_path:
            self._load_elo()

        # ── V6.2: 初始同步 ──
        if self._db and hasattr(self._db, "is_connected") and self._db.is_connected:
            # 这是一个异步过程, 但 __init__ 是同步的。
            # 复杂的同步通常在专门的 startup 流程中处理。
            # 这里我们提供 sync_with_db 方法供外部调用。
            pass

    async def sync_with_db(self) -> None:
        """从 SurrealDB 同步模型配置 (实现动态可调)。"""
        if not self._db or not hasattr(self._db, "load_model_cards"):
            return
        
        try:
            db_models = await self._db.load_model_cards()
            for m_data in db_models:
                # 转换 DB 数据为 ModelCard
                model_id = m_data.get("model_id")
                if not model_id: continue
                
                # 如果代码中已存在该模型，则进行属性覆盖（实现调节）
                # 如果不存在，则视为新增模型
                if model_id in self._models:
                    card = self._models[model_id]
                    # 只覆盖可调节字段
                    if "tier" in m_data: card.tier = ModelTier(m_data["tier"])
                    if "cost_per_mtok_in" in m_data: card.cost_per_mtok_in = m_data["cost_per_mtok_in"]
                    if "cost_per_mtok_out" in m_data: card.cost_per_mtok_out = m_data["cost_per_mtok_out"]
                    if "specialties" in m_data: card.specialties = m_data["specialties"]
                    if "display_name" in m_data: card.display_name = m_data["display_name"]
                    
                    # ── V6.5: 同步性能数据 ──
                    if "total_cost_spent" in m_data: card.total_cost_spent = m_data["total_cost_spent"]
                    if "advisor_success_count" in m_data: card.advisor_success_count = m_data["advisor_success_count"]
                    if "executor_success_count" in m_data: card.executor_success_count = m_data["executor_success_count"]
                else:
                    # 创建新模型
                    new_card = ModelCard(
                        model_id=model_id,
                        provider=m_data.get("provider", "unknown"),
                        display_name=m_data.get("display_name", model_id),
                        tier=ModelTier(m_data.get("tier", "workhorse")),
                        specialties=m_data.get("specialties", ["general"]),
                        cost_per_mtok_in=m_data.get("cost_per_mtok_in", 3.0),
                        cost_per_mtok_out=m_data.get("cost_per_mtok_out", 15.0),
                        api_key_env=m_data.get("api_key_env", ""),
                        openai_compatible=m_data.get("openai_compatible", True),
                        total_cost_spent=m_data.get("total_cost_spent", 0.0),
                        advisor_success_count=m_data.get("advisor_success_count", 0),
                        executor_success_count=m_data.get("executor_success_count", 0),
                    )
                    self._models[model_id] = new_card
            
            logger.info(f"🔄 ModelRegistry synced with DB: {len(db_models)} records.")
        except Exception as e:
            logger.error(f"Failed to sync ModelRegistry with DB: {e}")

    async def persist_defaults_to_db(self) -> None:
        """将当前内存中的默认模型同步到 DB (用于初始化调整列表)。"""
        if not self._db or not hasattr(self._db, "save_model_card"):
            return
        
        for card in self._models.values():
            await self._db.save_model_card(card.to_dict())

    def register(self, card: ModelCard) -> None:
        """注册或覆盖一个模型。"""
        self._models[card.model_id] = card

    def get(self, model_id: str) -> ModelCard | None:
        return self._models.get(model_id)

    def list_available(self) -> list[ModelCard]:
        """列出当前有 API Key 的可用模型。"""
        return [m for m in self._models.values() if m.is_available]

    def list_all(self) -> list[ModelCard]:
        return list(self._models.values())

    def find_by_tier(self, tier: ModelTier) -> list[ModelCard]:
        return [m for m in self.list_available() if m.tier == tier]

    def find_by_specialty(self, specialty: str) -> list[ModelCard]:
        """按专长找模型。"""
        return [
            m for m in self.list_available()
            if specialty in m.specialties
        ]

    def find_best_advisor(
        self,
        specialty: str | None = None,
        budget_per_call_usd: float = 1.0,
        exclude_providers: list[str] | None = None,
    ) -> list[ModelCard]:
        """
        找到最佳军师候选人。

        排序逻辑:
        1. Flagship 优先
        2. 专长匹配加权
        3. Elo 评分排序
        4. 预算内筛选
        """
        candidates = self.list_available()

        # 排除指定供应商
        if exclude_providers:
            candidates = [m for m in candidates if m.provider not in exclude_providers]

        # 预算筛选 (假设 1000 token 对话)
        candidates = [
            m for m in candidates
            if (m.cost_per_mtok_in * 0.001 + m.cost_per_mtok_out * 0.001) <= budget_per_call_usd
        ]

        # ──────────────────────────────────────────────
        # V6.5: Deep Elo Binding (非线性指数评分)
        # ──────────────────────────────────────────────
        import math

        def _score(m: ModelCard) -> float:
            # 基础分: e^(Elo / 200) 使高分模型产生断层优势
            elo_weight = math.exp(m.elo_advisor / 200.0)
            
            # 修正项
            tier_bonus = 1.2 if m.tier == ModelTier.FLAGSHIP else 1.0
            
            # ── V6.5: Tiered Routing Bonus ──
            # 军师优先选择 "high" 级别模型
            specific_bonus = 1.5 if m.specific_tier == "high" else 1.0
            
            specialty_bonus = 1.3 if specialty and specialty in m.specialties else 1.0
            
            # 效能修正 (实验性: 惩罚效率低下的模型)
            efficiency_multiplier = 1.0
            if m.advisor_matches > 5:  # 只有场次足够才修正
                efficiency_multiplier = min(1.2, max(0.8, m.efficiency_index / 100.0))

            return elo_weight * tier_bonus * specific_bonus * specialty_bonus * efficiency_multiplier

        candidates.sort(key=_score, reverse=True)
        return candidates

    def find_best_executor(
        self,
        specialty: str | None = None,
        budget_per_call_usd: float = 0.5,
    ) -> list[ModelCard]:
        """
        找到最佳特种兵候选人。

        偏好: Workhorse/Speed + 高 Elo
        """
        candidates = self.list_available()
        candidates = [
            m for m in candidates
            if (m.cost_per_mtok_in * 0.005 + m.cost_per_mtok_out * 0.005) <= budget_per_call_usd
        ]

        # ──────────────────────────────────────────────
        # V6.5: Deep Elo Binding (特种兵版)
        # ──────────────────────────────────────────────
        import math

        def _score(m: ModelCard) -> float:
            # 特种兵更看重响应速度和执行成功率
            elo_weight = math.exp(m.elo_executor / 150.0)
            
            tier_bonus = 1.1 if m.tier in [ModelTier.WORKHORSE, ModelTier.SPEED] else 0.9
            
            # ── V6.5: Tiered Routing Bonus (Executor) ──
            # 执行器优先选择 "low" (1.6x) 或 "standard" (1.3x) 级别模型以平衡成本
            if m.specific_tier == "low":
                specific_bonus = 1.6
            elif m.specific_tier == "standard":
                specific_bonus = 1.3
            else:
                specific_bonus = 1.0
            
            specialty_bonus = 1.2 if specialty and specialty in m.specialties else 1.0
            
            return elo_weight * tier_bonus * specific_bonus * specialty_bonus

        candidates.sort(key=_score, reverse=True)
        return candidates

    def update_elo(
        self,
        model_id: str,
        role: str,  # "advisor" / "executor"
        won: bool,
        k: float = 32.0,
    ) -> float:
        """
        更新模型的 Elo 评分。

        返回: 新的 Elo 评分。
        """
        card = self._models.get(model_id)
        if not card:
            raise ValueError(f"Model {model_id} not found in registry")

        if role == "advisor":
            card.advisor_matches += 1
            if won:
                card.advisor_wins += 1
            expected = 1.0 / (1.0 + 10 ** ((1500 - card.elo_advisor) / 400))
            actual = 1.0 if won else 0.0
            card.elo_advisor += k * (actual - expected)
            card.elo_advisor = max(800, min(2500, card.elo_advisor))
            self._save_elo()
            return card.elo_advisor
        else:
            card.executor_matches += 1
            if won:
                card.executor_wins += 1
            expected = 1.0 / (1.0 + 10 ** ((1500 - card.elo_executor) / 400))
            actual = 1.0 if won else 0.0
            card.elo_executor += k * (actual - expected)
            card.elo_executor = max(800, min(2500, card.elo_executor))
            self._save_elo()
            return card.elo_executor

    def update_metrics(
        self,
        model_id: str,
        role: str,
        cost_usd: float,
        success: bool,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> None:
        """更新模型效能数据。"""
        card = self._models.get(model_id)
        if not card: return
        
        card.total_cost_spent += cost_usd
        card.total_input_tokens += tokens_in
        card.total_output_tokens += tokens_out
        
        if success:
            if role == "advisor":
                card.advisor_success_count += 1
            else:
                card.executor_success_count += 1
        
        # 如果有 DB，异步持久化 (Fire and forget in this context)
        if self._db and hasattr(self._db, "save_model_card"):
            asyncio.create_task(self._db.save_model_card(card.to_dict()))

    def audit_fleet(self) -> list[str]:
        """
        全自动审计舰队。
        
        逻辑:
        1. 计算舰队平均效能指数 (Efficiency Index)
        2. 如果旗舰模型效能低于平均值的 50%，自动降级为 Workhorse
        3. 如果 Workhorse 效能低于平均值的 30%，标记为潜在淘汰对象
        """
        all_models = [m for m in self.list_all() if (m.advisor_matches + m.executor_matches) > 10]
        if not all_models:
            return ["Audit skipped: Not enough data (minimum 10 matches per model)."]
        
        avg_efficiency = sum(m.efficiency_index for m in all_models) / len(all_models)
        reports = [f"📊 Fleet Audit started. Avg Efficiency: {avg_efficiency:.4f}"]
        
        for m in self.list_all():
            matches = m.advisor_matches + m.executor_matches
            if matches < 10: continue
            
            # 1. 旗舰降级逻辑
            if m.tier == ModelTier.FLAGSHIP and m.efficiency_index < (avg_efficiency * 0.5):
                m.tier = ModelTier.WORKHORSE
                reports.append(f"⚠️ AUTO-DEMOTION: {m.display_name} downgraded to WORKHORSE (Efficiency: {m.efficiency_index:.4f})")
                if self._db:
                    asyncio.create_task(self._db.save_model_card(m.to_dict()))
            
            # 2. 旗舰晋升逻辑 (Auto-Promotion)
            elif m.tier == ModelTier.WORKHORSE and (m.efficiency_index > (avg_efficiency * 1.5) or m.elo_advisor > 1800):
                m.tier = ModelTier.FLAGSHIP
                reports.append(f"🚀 AUTO-PROMOTION: {m.display_name} promoted to FLAGSHIP (Efficiency: {m.efficiency_index:.4f}, Elo: {m.elo_advisor:.1f})")
                if self._db:
                    asyncio.create_task(self._db.save_model_card(m.to_dict()))

            # 3. 低效报警
            elif m.efficiency_index < (avg_efficiency * 0.2):
                reports.append(f"🚫 TOXIC ALERT: {m.display_name} is highly inefficient. Consider removal.")

        return reports

    def _load_elo(self) -> None:
        if self._elo_path and self._elo_path.exists():
            try:
                data = json.loads(self._elo_path.read_text(encoding="utf-8"))
                for model_id, scores in data.items():
                    card = self._models.get(model_id)
                    if card:
                        card.elo_advisor = scores.get("elo_advisor", 1500.0)
                        card.elo_executor = scores.get("elo_executor", 1500.0)
                        card.advisor_matches = scores.get("advisor_matches", 0)
                        card.executor_matches = scores.get("executor_matches", 0)
                        card.advisor_wins = scores.get("advisor_wins", 0)
                        card.executor_wins = scores.get("executor_wins", 0)
            except Exception as e:
                logger.warning(f"Failed to load Elo scores: {e}")

    def _save_elo(self) -> None:
        if not self._elo_path:
            return
        self._elo_path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        for model_id, card in self._models.items():
            if card.advisor_matches > 0 or card.executor_matches > 0:
                data[model_id] = {
                    "elo_advisor": card.elo_advisor,
                    "elo_executor": card.elo_executor,
                    "advisor_matches": card.advisor_matches,
                    "executor_matches": card.executor_matches,
                    "advisor_wins": card.advisor_wins,
                    "executor_wins": card.executor_wins,
                }
        self._elo_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def get_leaderboard(self, role: str = "advisor", top_k: int = 10) -> list[dict[str, Any]]:
        """生成排行榜。"""
        models = list(self._models.values())
        if role == "advisor":
            models.sort(key=lambda m: m.elo_advisor, reverse=True)
            return [
                {
                    "rank": i + 1,
                    "model": m.display_name,
                    "provider": m.provider,
                    "elo": m.elo_advisor,
                    "matches": m.advisor_matches,
                    "win_rate": f"{m.advisor_win_rate:.1%}",
                }
                for i, m in enumerate(models[:top_k])
            ]
        else:
            models.sort(key=lambda m: m.elo_executor, reverse=True)
            return [
                {
                    "rank": i + 1,
                    "model": m.display_name,
                    "provider": m.provider,
                    "elo": m.elo_executor,
                    "matches": m.executor_matches,
                    "win_rate": f"{m.executor_win_rate:.1%}",
                }
                for i, m in enumerate(models[:top_k])
            ]


# ════════════════════════════════════════════
#  军师-特种兵路由引擎 (核心)
# ════════════════════════════════════════════

class AdvisorExecutorRouter:
    """
    军师-特种兵智能路由引擎。

    超越 Anthropic:
    1. 任意模型任意搭配
    2. 4 种策略 (Solo/Council/Debate/Cascade)
    3. 按领域自动匹配最佳军师
    4. Elo 反馈闭环
    5. 动态预算感知
    """

    # 级联策略的默认置信度阈值
    CASCADE_CONFIDENCE_THRESHOLD = 0.7
    # 辩论协议的默认轮数
    DEBATE_ROUNDS = 3
    # 会议的默认军师数量
    COUNCIL_SIZE = 3

    def __init__(
        self,
        registry: ModelRegistry,
        caller_factory: Any = None,
    ):
        self._registry = registry
        self._caller_factory = caller_factory  # create_caller 函数
        self._pairing_counter = 0

    def _create_caller(self, card: ModelCard) -> BaseLLM:
        """根据 ModelCard 创建 LLM Caller 实例。"""
        # 获取 API Key: 优先 ModelCard 指定的 env var, 其次 IDE 注入的 token
        api_key = os.getenv(card.api_key_env, "")
        if not api_key and os.getenv("Coda_AGENT") == "1":
            # IDE 环境: 使用 IDE 注入的认证 token
            api_key = os.getenv("ANTHROPIC_AUTH_TOKEN", "")

        if self._caller_factory:
            return self._caller_factory(card.model_id, api_key)

        # 内建工厂
        from .llm_caller import create_caller
        return create_caller(card.model_id, api_key)

    def select_strategy(
        self,
        risk_level: str = "medium",
        budget_usd: float = 1.0,
    ) -> AdvisorStrategy:
        """
        根据风险等级和预算自动选择策略。

        high risk + high budget → Council/Debate
        medium risk → Solo
        low risk + low budget → Cascade
        """
        if risk_level == "critical" and budget_usd >= 0.5:
            return AdvisorStrategy.DEBATE
        if risk_level == "high" and budget_usd >= 0.3:
            return AdvisorStrategy.COUNCIL
        if risk_level == "low" or budget_usd < 0.1:
            return AdvisorStrategy.CASCADE
        return AdvisorStrategy.SOLO

    async def consult(
        self,
        task_context: str,
        strategy: AdvisorStrategy | None = None,
        specialty: str | None = None,
        risk_level: str = "medium",
        budget_usd: float = 1.0,
        executor_hint: str | None = None,
    ) -> AdvisorVerdict:
        """
        执行军师咨询。

        这是核心入口:
        1. 自动选择策略 (如果未指定)
        2. 路由到最佳军师
        3. 执行策略 (Solo/Council/Debate/Cascade)
        4. 返回聚合裁决
        """
        # 1. 尝试连接 IDE Bridge 以获取实时配额
        if os.getenv("Coda_AGENT") == "1":
            try:
                from .ide_bridge import IDEBridge
                bridge = await IDEBridge.get_or_connect()
                if bridge.is_connected:
                    logger.debug("IDE Bridge connected. Active models: %d", 
                               len(bridge.get_available_models()))
            except Exception as e:
                logger.warning("Failed to connect to IDE Bridge (quota checks disabled): %s", e)

        if strategy is None:
            strategy = self.select_strategy(risk_level, budget_usd)

        self._pairing_counter += 1
        pairing_id = f"pair-{int(time.time())}-{self._pairing_counter}"

        logger.info(
            f"🧠 Advisor consultation started | Strategy={strategy.value} | "
            f"Risk={risk_level} | Budget=${budget_usd:.2f}"
        )

        # ── V6.5: 每 50 次咨询执行一次全自动审计 ──
        if self._pairing_counter % 50 == 0:
            reports = self._registry.audit_fleet()
            for r in reports:
                logger.info(f"[Registry Audit] {r}")

        if strategy == AdvisorStrategy.SOLO:
            return await self._strategy_solo(task_context, specialty, budget_usd, pairing_id)
        elif strategy == AdvisorStrategy.COUNCIL:
            return await self._strategy_council(task_context, specialty, budget_usd, pairing_id)
        elif strategy == AdvisorStrategy.DEBATE:
            return await self._strategy_debate(task_context, specialty, budget_usd, pairing_id)
        elif strategy == AdvisorStrategy.CASCADE:
            return await self._strategy_cascade(task_context, specialty, budget_usd, pairing_id)
        else:
            return await self._strategy_solo(task_context, specialty, budget_usd, pairing_id)

    async def _call_advisor(
        self,
        card: ModelCard,
        prompt: str,
        system_prompt: str = "",
    ) -> AdvisorOpinion:
        """调用单个军师模型 (快捷方法)。"""
        caller = self._create_caller(card)
        return await self._call_advisor_instance(card, caller, prompt, system_prompt)

    async def _call_advisor_instance(
        self,
        card: ModelCard,
        caller: BaseLLM,
        prompt: str,
        system_prompt: str = "",
    ) -> AdvisorOpinion:
        """调用已实例化的军师模型。"""
        start = time.time()
        try:
            messages: list[dict[str, Any]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            response = await caller.call(messages, temperature=0.3)
            elapsed = (time.time() - start) * 1000
            cost = (
                response.input_tokens * card.cost_per_mtok_in
                + response.output_tokens * card.cost_per_mtok_out
            ) / 1_000_000

            # 解析裁决
            verdict, confidence, reasoning = self._parse_advisor_response(response.text)
            
            # ── V6.5: 记录基础指标 ──
            self._registry.update_metrics(
                card.model_id, role="advisor", cost_usd=cost, 
                success=False,
                tokens_in=response.input_tokens, tokens_out=response.output_tokens
            )

            return AdvisorOpinion(
                model_id=card.model_id,
                provider=card.provider,
                verdict=verdict,
                reasoning=reasoning,
                confidence=confidence,
                cost_usd=cost,
                latency_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            logger.error(f"Advisor call to {card.display_name} failed: {e}")
            return AdvisorOpinion(
                model_id=card.model_id,
                provider=card.provider,
                verdict="escalate",
                reasoning=f"Advisor call failed: {e}",
                confidence=0.0,
                latency_ms=elapsed,
            )

    def record_result(
        self,
        pairing_id: str,
        verdict: AdvisorVerdict,
        success: bool,
    ) -> None:
        """
        全自动闭环反馈核心。
        
        当业务执行完成后，通过此方法反馈该次咨询/执行是否成功。
        1. 更新 Elo 评分
        2. 更新成功/失败计数 (Efficiency Profiler)
        """
        logger.info(f"🔄 Recording result for {pairing_id}: Success={success}")
        
        for op in verdict.opinions:
            role = "advisor" 
            # 更新 Elo
            self._registry.update_elo(op.model_id, role=role, won=success)
            # 更新效能指标 (这里补偿之前 _call_advisor 录入的 success=False)
            self._registry.update_metrics(op.model_id, role=role, cost_usd=0, success=success)
            
        if verdict.suggested_executor:
            # 如果也用了执行器，更新其执行器 Elo
            # 注意: 常规逻辑中 executor 是在 consult 之外配对的，
            # 这里的 suggested_executor 仅为建议。实际系统应在执行器完成后调用此方法。
            pass

    def _parse_advisor_response(self, text: str) -> tuple[str, float, str]:
        """
        解析军师的自然语言响应。

        尝试从 JSON 或结构化标签中提取裁决。
        """
        text_lower = text.lower()

        # 尝试 JSON 解析
        try:
            import re
            json_match = re.search(r'\{[^{}]*"verdict"[^{}]*\}', text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return (
                    str(data.get("verdict", "refine")),
                    float(data.get("confidence", 0.8)),
                    str(data.get("reasoning", text[:500])),
                )
        except (json.JSONDecodeError, ValueError):
            pass

        # 关键词匹配
        if any(w in text_lower for w in ["approve", "批准", "通过", "lgtm"]):
            return "approve", 0.85, text[:500]
        if any(w in text_lower for w in ["abort", "拒绝", "阻止", "block"]):
            return "abort", 0.85, text[:500]
        if any(w in text_lower for w in ["refine", "修改", "调整", "改进"]):
            return "refine", 0.75, text[:500]

        return "refine", 0.6, text[:500]

    # ──────────────── 策略实现 ────────────────

    async def _strategy_solo(
        self, context: str, specialty: str | None, budget: float, pairing_id: str
    ) -> AdvisorVerdict:
        """Solo 策略: 选择 1 位最优军师。"""
        advisors = self._registry.find_best_advisor(specialty, budget)
        if not advisors:
            return AdvisorVerdict(
                verdict="refine",
                reasoning="No suitable advisors found for this specialty/budget criteria.",
                confidence=0.5,
                strategy_used=AdvisorStrategy.SOLO,
                pairing_id=pairing_id,
            )

        advisor = advisors[0]
        # ── V6.5: [HT-TRACE] 识别身份 ──
        # 优先显示是否使用了 IDE 集成身份
        account_name = advisor.api_key_env if os.getenv(advisor.api_key_env) else "Coda IDE Identity"
        logger.info(f"👤 HT-TRACE | Account={account_name} | Advisor={advisor.display_name}")
        
        caller = self._create_caller(advisor)
        opinion = await self._call_advisor_instance(
            advisor,
            caller,
            self._build_advisor_prompt(context),
            self._build_system_prompt("solo"),
        )

        return AdvisorVerdict(
            verdict=opinion.verdict,
            reasoning=opinion.reasoning,
            confidence=opinion.confidence,
            strategy_used=AdvisorStrategy.SOLO,
            cost_usd=opinion.cost_usd,
            total_latency_ms=opinion.latency_ms,
            opinions=[opinion],
            suggested_executor=self._suggest_executor(specialty, budget),
            pairing_id=pairing_id,
            handover_pkt=UniversalCognitivePacket(
                source=SovereignIdentity(
                    instance_id=advisor.model_id,
                    role_id="advisor",
                    owner_did=caller.owner_identity  # 使用真实探测到的 ID
                ),
                objective=opinion.verdict,
                instruction=opinion.reasoning[:1000],
                packet_type="verification_result",
                domain_payload={"pairing_id": pairing_id, "strategy": "solo"}
            )
        )

    async def _strategy_council(
        self, context: str, specialty: str | None, budget: float, pairing_id: str
    ) -> AdvisorVerdict:
        """Council 策略: 多军师并行审议 + 投票。"""
        per_advisor_budget = budget / self.COUNCIL_SIZE
        advisors = self._registry.find_best_advisor(specialty, per_advisor_budget)
        council = advisors[:self.COUNCIL_SIZE]

        if len(council) < 2:
            return await self._strategy_solo(context, specialty, budget, pairing_id)

        # 并行调用所有军师
        tasks = [
            self._call_advisor(
                advisor,
                self._build_advisor_prompt(context),
                self._build_system_prompt("council"),
            )
            for advisor in council
        ]
        opinions = await asyncio.gather(*tasks)

        # 投票
        vote_tally: dict[str, int] = {}
        total_cost = 0.0
        max_latency = 0.0
        for opinion in opinions:
            vote_tally[opinion.verdict] = vote_tally.get(opinion.verdict, 0) + 1
            total_cost += opinion.cost_usd
            max_latency = max(max_latency, opinion.latency_ms)

        # 多数决
        final_verdict = max(vote_tally, key=vote_tally.get)  # type: ignore[arg-type]
        dissent = [o for o in opinions if o.verdict != final_verdict]
        avg_confidence = sum(o.confidence for o in opinions) / len(opinions)

        # 合并推理
        reasoning_parts = [
            f"[{o.provider}/{o.model_id}] {o.verdict}: {o.reasoning[:200]}"
            for o in opinions
        ]
        combined_reasoning = (
            f"Council ({len(council)} advisors) voted: {vote_tally}.\n"
            + "\n".join(reasoning_parts)
        )

        return AdvisorVerdict(
            verdict=final_verdict,
            reasoning=combined_reasoning,
            confidence=avg_confidence,
            strategy_used=AdvisorStrategy.COUNCIL,
            cost_usd=total_cost,
            total_latency_ms=max_latency,
            opinions=list(opinions),
            dissenting_opinions=dissent,
            vote_tally=vote_tally,
            suggested_executor=self._suggest_executor(specialty, budget),
            pairing_id=pairing_id,
        )

    async def _strategy_debate(
        self, context: str, specialty: str | None, budget: float, pairing_id: str
    ) -> AdvisorVerdict:
        """Debate 策略: 正方 vs 反方辩论, 最终由裁判裁决。"""
        per_role_budget = budget / 3  # 正方 + 反方 + 裁判
        advisors = self._registry.find_best_advisor(specialty, per_role_budget)

        if len(advisors) < 2:
            return await self._strategy_solo(context, specialty, budget, pairing_id)

        proponent = advisors[0]
        opponent = advisors[1] if advisors[1].provider != proponent.provider else (
            advisors[2] if len(advisors) > 2 else advisors[1]
        )

        # 第一轮辩论
        pro_opinion = await self._call_advisor(
            proponent,
            self._build_advisor_prompt(context),
            "你是正方军师。请论证这个方案的可行性和优势。输出 JSON: {\"verdict\": \"approve\"/\"refine\", \"confidence\": 0.0-1.0, \"reasoning\": \"...\"}",
        )
        con_opinion = await self._call_advisor(
            opponent,
            self._build_advisor_prompt(context) + f"\n\n[正方论据]: {pro_opinion.reasoning[:500]}",
            "你是反方军师。请论证这个方案的风险和弱点。输出 JSON: {\"verdict\": \"abort\"/\"refine\", \"confidence\": 0.0-1.0, \"reasoning\": \"...\"}",
        )

        total_cost = pro_opinion.cost_usd + con_opinion.cost_usd
        max_latency = max(pro_opinion.latency_ms, con_opinion.latency_ms)

        # 裁判裁决 (选择正方作为裁判，实际中应用第三方)
        if pro_opinion.confidence > con_opinion.confidence:
            final_verdict = pro_opinion.verdict
            reasoning = f"Debate: 正方胜 (Confidence: {pro_opinion.confidence:.2f} vs {con_opinion.confidence:.2f})"
        else:
            final_verdict = con_opinion.verdict
            reasoning = f"Debate: 反方胜 (Confidence: {con_opinion.confidence:.2f} vs {pro_opinion.confidence:.2f})"

        reasoning += f"\n[正方 {proponent.display_name}]: {pro_opinion.reasoning[:300]}"
        reasoning += f"\n[反方 {opponent.display_name}]: {con_opinion.reasoning[:300]}"

        return AdvisorVerdict(
            verdict=final_verdict,
            reasoning=reasoning,
            confidence=max(pro_opinion.confidence, con_opinion.confidence),
            strategy_used=AdvisorStrategy.DEBATE,
            cost_usd=total_cost,
            total_latency_ms=max_latency,
            opinions=[pro_opinion, con_opinion],
            dissenting_opinions=[con_opinion] if final_verdict == pro_opinion.verdict else [pro_opinion],
            pairing_id=pairing_id,
        )

    async def _strategy_cascade(
        self, context: str, specialty: str | None, budget: float, pairing_id: str
    ) -> AdvisorVerdict:
        """Cascade 策略: 便宜先审, 不确定时逐级升级。"""
        tiers = [ModelTier.SPEED, ModelTier.WORKHORSE, ModelTier.FLAGSHIP]
        total_cost = 0.0
        total_latency = 0.0

        for tier in tiers:
            candidates = [
                m for m in self._registry.list_available()
                if m.tier == tier
            ]
            if not candidates:
                continue

            # 选成本最低的
            candidates.sort(key=lambda m: m.cost_score)
            advisor = candidates[0]

            opinion = await self._call_advisor(
                advisor,
                self._build_advisor_prompt(context),
                self._build_system_prompt("cascade"),
            )
            total_cost += opinion.cost_usd
            total_latency += opinion.latency_ms

            if opinion.confidence >= self.CASCADE_CONFIDENCE_THRESHOLD:
                logger.info(
                    f"Cascade resolved at tier={tier.value} ({advisor.display_name}) "
                    f"with confidence={opinion.confidence:.2f}"
                )
                return AdvisorVerdict(
                    verdict=opinion.verdict,
                    reasoning=f"[Cascade @ {tier.value}] {opinion.reasoning}",
                    confidence=opinion.confidence,
                    strategy_used=AdvisorStrategy.CASCADE,
                    cost_usd=total_cost,
                    total_latency_ms=total_latency,
                    opinions=[opinion],
                    suggested_executor=self._suggest_executor(specialty, budget),
                    pairing_id=pairing_id,
                )

            logger.info(
                f"Cascade: {advisor.display_name} uncertain (conf={opinion.confidence:.2f}), escalating..."
            )

        # 所有级别都不确定
        return AdvisorVerdict(
            verdict="escalate",
            reasoning="All cascade tiers returned low confidence. Human review recommended.",
            confidence=0.3,
            strategy_used=AdvisorStrategy.CASCADE,
            cost_usd=total_cost,
            total_latency_ms=total_latency,
            pairing_id=pairing_id,
        )

    def _suggest_executor(self, specialty: str | None, budget: float) -> str:
        """推荐最佳特种兵。"""
        executors = self._registry.find_best_executor(specialty, budget)
        return executors[0].model_id if executors else ""

    def _build_advisor_prompt(self, context: str) -> str:
        return (
            "请作为高阶技术军师审议以下方案。\n\n"
            f"[方案上下文]:\n{context}\n\n"
            "[输出要求]:\n"
            '请输出 JSON: {"verdict": "approve"/"refine"/"abort", '
            '"confidence": 0.0-1.0, "reasoning": "你的分析"}'
        )

    def _build_system_prompt(self, strategy: str) -> str:
        if strategy == "solo":
            return (
                "你是一位顶级技术军师 (Advisor)。你的职责是审计执行方案的可行性、风险与优化空间。"
                "请基于你的专业知识给出客观、准确的裁决。"
            )
        if strategy == "council":
            return (
                "你是军师会议 (Council) 的一名成员。请独立给出你的裁决，不要受其他军师影响。"
                "你的投票将与其他军师的投票合并计算。"
            )
        if strategy == "cascade":
            return (
                "你是级联审计 (Cascade) 中的一环。如果你对裁决有高置信度 (>=0.7) 请直接裁决。"
                "如果不确定，请设置低置信度，系统会自动升级到更高级的军师。"
            )
        return "你是一位技术军师。请审议并给出你的裁决。"

    def record_outcome(self, pairing_id: str, verdict: AdvisorVerdict, success: bool) -> None:
        """记录搭配结果并更新 Elo。"""
        for opinion in verdict.opinions:
            self._registry.update_elo(opinion.model_id, "advisor", success)

        if verdict.suggested_executor:
            self._registry.update_elo(verdict.suggested_executor, "executor", success)

        logger.info(
            f"📊 Pairing {pairing_id} recorded: success={success}, "
            f"advisors={[o.model_id for o in verdict.opinions]}"
        )
