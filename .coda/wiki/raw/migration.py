"""
Coda V4.0 — Model Evolution & Migration (Pillar 22)
模型进化平滑迁移: 当新模型发布时, 自动迁移配置和上下文。

设计参考: 原始 TS `migrations/migrateSonnet45ToSonnet46.ts`

同时包含 Beta Feature Flags (灰度特性开关) 的管理逻辑。
"""

from __future__ import annotations

import logging
import time
import json
from collections.abc import Mapping, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast, Any, TypedDict

if TYPE_CHECKING:
    from .db import SurrealStore

logger = logging.getLogger("Coda.memory")
logging.getLogger("Coda.migration")


@dataclass
class ModelProfile:
    """模型配置档案。"""
    name: str
    max_tokens: int = 128000
    supports_tools: bool = True
    supports_vision: bool = False
    cost_per_million_input: float = 3.0
    cost_per_million_output: float = 15.0
    default_temperature: float = 0.7

# 已知模型注册表
MODEL_REGISTRY: dict[str, ModelProfile] = {
    "gemini-2.5-pro": ModelProfile("gemini-2.5-pro", 1_000_000, True, True, 1.25, 10.0),
    "gemini-2.5-flash": ModelProfile("gemini-2.5-flash", 1_000_000, True, True, 0.15, 0.6),
    "claude-sonnet-4": ModelProfile("claude-sonnet-4", 200_000, True, True, 3.0, 15.0),
    "claude-opus-4": ModelProfile("claude-opus-4", 200_000, True, True, 15.0, 75.0),
    "gpt-4o": ModelProfile("gpt-4o", 128_000, True, True, 5.0, 15.0),
}

# 迁移路径定义
MIGRATION_PATHS: dict[str, str] = {
    "gemini-2.0-pro": "gemini-2.5-pro",
    "gemini-2.0-flash": "gemini-2.5-flash",
    "claude-sonnet-3.5": "claude-sonnet-4",
    "claude-opus-3": "claude-opus-4",
    "gpt-4-turbo": "gpt-4o",
}


class MigrationLog(TypedDict):
    success: bool
    from_model: str
    to_model: str
    changes: list[str]
    reason: str | None

class ModelMigrator:
    """
    模型进化平滑迁移器 (Pillar 22)。

    当 OpenAI 或 Anthropic 发布新模型时,
    系统自动识别并迁移当前的权限设定、记忆上下文与配置,
    实现真正的"零感知"智力升级。
    """

    def __init__(self, config_dir: str | Path):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def get_profile(self, model_name: str) -> ModelProfile | None:
        """获取模型配置档案。"""
        return MODEL_REGISTRY.get(model_name)

    def check_migration(self, current_model: str) -> str | None:
        """检查是否有可用的模型升级路径。"""
        return MIGRATION_PATHS.get(current_model)

    def migrate(self, old_model: str, new_model: str) -> MigrationLog | dict[str, object]:
        """
        执行模型迁移。

        自动迁移:
        - 权限设定
        - Token 预算 (按新模型调整)
        - 成本计算参数
        """
        old_profile = self.get_profile(old_model)
        new_profile = self.get_profile(new_model)

        if not new_profile:
            return {"success": False, "reason": f"Unknown target model: {new_model}"}

        migration_log: MigrationLog = {
            "success": True,
            "from_model": old_model,
            "to_model": new_model,
            "changes": [],
            "reason": None,
        }

        # Token 限制迁移
        if old_profile and new_profile.max_tokens != old_profile.max_tokens:
            migration_log["changes"].append(
                f"max_tokens: {old_profile.max_tokens} → {new_profile.max_tokens}"
            )

        # 成本参数迁移
        if old_profile and new_profile.cost_per_million_input != old_profile.cost_per_million_input:
            migration_log["changes"].append(
                f"cost_input: ${old_profile.cost_per_million_input}/M → ${new_profile.cost_per_million_input}/M"
            )

        # 保存迁移记录
        log_file = self.config_dir / "migration_history.jsonl"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(migration_log, ensure_ascii=False) + "\n")

        logger.info(f"🔄 Model migrated: {old_model} → {new_model} ({len(migration_log['changes'])} changes)")
        return migration_log


class BetaFlags:
    """
    灰度特性开关 (Beta Feature Flags)。

    允许 Agent 动态开启某些高阶但不稳定的功能,
    实现"试错与渐进式测试"的能力。
    """

    def __init__(self, config_dir: str | Path):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._flags: dict[str, bool] = {}
        self._load()

    def _load(self) -> None:
        """从配置文件加载灰度标志。"""
        flag_file = self.config_dir / "beta_flags.json"
        if flag_file.exists():
            try:
                self._flags = json.loads(flag_file.read_text(encoding="utf-8"))
            except Exception:
                self._flags = {}

    def _save(self) -> None:
        """保存灰度标志到配置文件。"""
        flag_file = self.config_dir / "beta_flags.json"
        flag_file.write_text(json.dumps(self._flags, indent=2), encoding="utf-8")

    def enable(self, flag: str) -> None:
        """启用灰度特性。"""
        self._flags[flag] = True
        self._save()
        logger.info(f"🧪 Beta enabled: {flag}")

    def disable(self, flag: str) -> None:
        """禁用灰度特性。"""
        self._flags[flag] = False
        self._save()

    def is_enabled(self, flag: str) -> bool:
        """检查灰度特性是否启用。"""
        return self._flags.get(flag, False)

    def list_flags(self) -> dict[str, bool]:
        """列出所有灰度标志。"""
        return dict(self._flags)

    # 预定义的灰度特性
    AGGRESSIVE_REFACTOR = "aggressive_refactor"       # 更激进的代码重构策略
    SPECULATIVE_PRELOAD = "speculative_preload"       # 预判式调用 (Sonnet + Haiku)
    CAUSAL_REASONING = "causal_reasoning"             # 因果链学习与错误自愈
    MODULAR_PROMPT = "modular_prompt"                 # 模块化 Prompt Pooling (缓存优化)
    SWARM_CORE = "swarm_core"                         # 集群协作核心
    AUTO_SKILLIFY = "auto_skillify"                   # 自动技能固化
    SWARM_MODE = "swarm_mode"                         # 集群协作模式
    VOICE_MODE = "voice_mode"                         # 语音交互模式 (预留)
