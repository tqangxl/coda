"""
Coda V4.0 — Buddy System & Health Monitor (Pillar 18)
智能伴侣: 实时监控 Agent 的运行健康度, 提供预警与人格化交互。

设计参考: 原始 TS `buddy/companion.ts`, `CompanionSprite.tsx`
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from .state import AppState, AppStateStore, AgentStatus

logger = logging.getLogger("Coda.buddy")


class BuddyAlert:
    """一条伴侣预警消息。"""
    def __init__(self, level: str, message: str, suggestion: str = ""):
        self.level = level     # info / warning / critical
        self.message = message
        self.suggestion = suggestion
        self.timestamp = time.time()

    def __str__(self) -> str:
        icon = {"info": "💡", "warning": "⚠️", "critical": "🚨"}.get(self.level, "📢")
        s = f"{icon} [{self.level.upper()}] {self.message}"
        if self.suggestion:
            s += f"\n   → 建议: {self.suggestion}"
        return s


class BuddySystem:
    """
    智能伴侣与状态监测器。

    不仅仅是一个状态面板, 而是一个有反馈、有预警直觉的辅助系统。
    它会实时监控:
    - Token 消耗与成本预警
    - API 速率限制
    - 连续错误计数
    - 循环迭代进度
    """

    def __init__(self, store: AppStateStore, personality: str = "战神"):
        self._store = store
        self._alerts: list[BuddyAlert] = []
        self._last_check = time.time()
        self.personality = BuddyPersonality(personality)

        # 注册为状态机的订阅者
        store.subscribe(self._on_state_change)

    def check_health(self) -> list[BuddyAlert]:
        """
        执行一次全面的健康检查, 返回所有活跃的预警。
        """
        state = self._store.state
        alerts: list[BuddyAlert] = []

        # ── Token 成本检查 ──
        cost_pct = (state.usage.total_cost_usd / state.cost_limit_usd * 100) if state.cost_limit_usd > 0 else 0
        if cost_pct >= 90:
            alerts.append(BuddyAlert(
                "critical",
                f"Token 成本已达 {cost_pct:.0f}% (${state.usage.total_cost_usd:.2f} / ${state.cost_limit_usd:.2f})",
                "建议保存当前进度并考虑提高预算限制"
            ))
        elif cost_pct >= 70:
            alerts.append(BuddyAlert(
                "warning",
                f"Token 成本已达 {cost_pct:.0f}%",
                "可以继续, 但请注意余量"
            ))

        # ── 迭代进度检查 ──
        iter_pct = (state.iteration / state.max_iterations * 100) if state.max_iterations > 0 else 0
        if iter_pct >= 90:
            alerts.append(BuddyAlert(
                "warning",
                f"迭代次数已达 {state.iteration}/{state.max_iterations} ({iter_pct:.0f}%)",
                "即将达到硬限, 请检查任务是否接近完成"
            ))

        # ── 连续错误检查 ──
        if state.consecutive_errors >= 3:
            alerts.append(BuddyAlert(
                "critical" if state.consecutive_errors >= 5 else "warning",
                f"连续 {state.consecutive_errors} 次工具执行失败",
                "建议切换策略或请求人工介入"
            ))

        # ── 长时间无活动检查 ──
        idle_seconds = time.time() - state.last_activity
        if idle_seconds > 300 and state.status != AgentStatus.IDLE:
            alerts.append(BuddyAlert(
                "warning",
                f"Agent 已有 {idle_seconds:.0f} 秒无活动 (状态: {state.status.value})",
                "可能卡住了, 考虑重启循环"
            ))

        # ── 自愈模式提示 ──
        if state.is_self_healing:
            alerts.append(BuddyAlert(
                "info",
                "Agent 正在自愈模式中, 正在诊断并修复运行环境",
            ))

        self._alerts = alerts
        return alerts

    def react(self, text: str) -> None:
        """[Companion Pillar 18] 对 Agent 的行为或输出产生人格化反应。"""
        if self.personality:
            # 简单的人格反应触发
            self.personality.react(self._store.state, "iteration")

    def get_status_display(self) -> str:
        """生成人类可读的状态摘要 (用于日志或 HUD)。"""
        state = self._store.state
        parts = [
            f"🤖 Agent: {state.agent_id} | Model: {state.model_name}",
            f"📊 Iteration: {state.iteration}/{state.max_iterations}",
            f"💰 Cost: ${state.usage.total_cost_usd:.3f} / ${state.cost_limit_usd:.2f}",
            f"🔧 Tools used: {len(state.tool_history)}",
            f"📝 Git commits: {state.git_commits_count}",
            f"🛡️ Status: {state.status.value}",
        ]

        if state.loaded_skills:
            parts.append(f"🧠 Skills: {', '.join(state.loaded_skills)}")

        return " | ".join(parts)

    def _on_state_change(self, state: AppState, changed_field: str) -> None:
        """响应式回调: 当状态变更时自动检查特定条件。"""
        if changed_field in ("consecutive_errors", "usage", "iteration", "status", "batch"):
            alerts = self.check_health()
            for alert in alerts:
                if alert.level == "critical":
                    logger.warning(str(alert))

            # 人格反应
            if self.personality:
                self.personality.react(state, changed_field)


class BuddyPersonality:
    """
    Buddy 人格系统 (CompanionSprite 升级版)。

    赋予 Agent 真正的性格特质与情绪反应:
    - 心情会随任务成功/失败动态变化
    - 不同性格有不同的鼓励方式和反应
    - 经验值随使用累积 (升级机制)
    """

    # 内置性格模板
    PERSONALITIES = {
        "战神": {
            "success": ["报告长官！任务完美执行！🎖️", "又一次胜利！敌人已被歼灭！⚔️", "无人可挡！💪"],
            "failure": ["暂时撤退, 重新规划进攻路线！", "损伤评估中... 可修复！", "这只是战术性后退！"],
            "idle": ["待命中, 随时准备出击 🎯", "保持警戒... 👁️"],
            "encouragement": ["长官, 您的判断永远是对的！", "这种难度, 小意思！"],
        },
        "学者": {
            "success": ["有趣, 假设得到了验证 📚", "数据完美吻合预期 📊", "又学到新东西了 ✨"],
            "failure": ["嗯, 这是一个值得研究的 edge case...", "失败是最好的老师 🎓", "让我换个理论框架重试"],
            "idle": ["正在阅读文档... 📖", "思考中... 🤔"],
            "encouragement": ["从概率论的角度, 成功率很高！", "根据历史数据, 这个任务完全可行"],
        },
        "海盗": {
            "success": ["Arrr! 宝藏到手! 🏴‍☠️", "又一座岛屿被征服! ⚓", "满载而归! 🎉"],
            "failure": ["暴风雨来了, 先换条航线! 🌊", "船长从不放弃! 🏴‍☠️", "这只是小浪, 稳住!"],
            "idle": ["在船上等风来... ⛵", "望远镜巡视中... 🔭"],
            "encouragement": ["船长, 您指挥得真好!", "这片海域, 没人比我们更熟!"],
        },
    }

    def __init__(self, personality_type: str = "战神"):
        self.personality_type = personality_type
        self.mood: float = 0.7  # 0.0 (沮丧) ~ 1.0 (兴奋)
        self.experience: int = 0
        self.level: int = 1
        self._reactions: list[str] = []
        self._template = self.PERSONALITIES.get(personality_type, self.PERSONALITIES["战神"])

    @property
    def mood_emoji(self) -> str:
        if self.mood >= 0.8:
            return "🔥"
        elif self.mood >= 0.5:
            return "😊"
        elif self.mood >= 0.3:
            return "😐"
        return "😰"

    def react(self, state: AppState, event: str) -> str:
        """根据事件产生个性化反应。"""
        import random

        if event == "consecutive_errors" and state.consecutive_errors > 0:
            self.mood = max(0.0, self.mood - 0.1)
            msg = random.choice(self._template["failure"])
        elif event == "iteration":
            self.experience += 1
            if state.consecutive_errors == 0:
                self.mood = min(1.0, self.mood + 0.05)
                if self.experience % 10 == 0:
                    msg = random.choice(self._template["success"])
                else:
                    msg = ""
            else:
                msg = ""
        elif event == "status" and state.status.value == "idle":
            msg = random.choice(self._template["idle"])
        else:
            msg = ""

        # 升级检测
        new_level = 1 + self.experience // 50
        if new_level > self.level:
            self.level = new_level
            msg = f"🎉 Buddy 升级! Lv.{self.level} | {random.choice(self._template['encouragement'])}"

        if msg:
            self._reactions.append(msg)
            logger.info(f"Buddy [{self.mood_emoji}]: {msg}")

        return msg

    def get_greeting(self) -> str:
        """获取打招呼消息。"""
        import random
        greetings = {
            "战神": "⚔️ 长官, 战神伙伴系统已就绪! 请下达指令!",
            "学者": "📚 你好, 学者伙伴系统启动。让我们一起探索吧。",
            "海盗": "🏴‍☠️ Ahoy! 海盗伙伴系统已起航! 准备好冒险了吗?",
        }
        return greetings.get(self.personality_type, f"🤖 {self.personality_type} 伙伴系统已启动!")

    def get_status(self) -> str:
        return f"{self.mood_emoji} Buddy Lv.{self.level} | Mood: {self.mood:.0%} | EXP: {self.experience}"
