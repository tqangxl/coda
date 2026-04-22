"""
Coda V4.0 — Prompt Speculation (Pillar 16 & 28)
指令预判与加速: Agent 在后台"静默推演"用户下一步可能的需求。

设计参考: 原始 TS `services/PromptSuggestion/speculation.ts`
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from collections.abc import Sequence, Mapping
from typing import Optional

logger = logging.getLogger("Coda.speculation")


class SpeculationHint:
    """一条预判提示。"""
    def __init__(self, hint_type: str, content: str, confidence: float = 0.5):
        self.hint_type = hint_type   # file_preload, next_action, related_context
        self.content = content
        self.confidence = confidence

    def __repr__(self) -> str:
        return f"Hint({self.hint_type}, conf={self.confidence:.1f})"


class PromptSpeculation:
    """
    指令预判系统 (Pillar 28: Predictive Sensing)。

    Agent 在执行当前命令时, 后台静默推演用户下一步可能的提问,
    预先加载相关文件或逻辑分级, 实现毫秒级的响应反馈感。
    """

    def __init__(self, working_dir: str | Path):
        self.working_dir = Path(working_dir)
        self._file_access_history: list[str] = []

    def speculate(self, recent_messages: Sequence[Mapping[str, object]], recent_files: Sequence[str]) -> list[SpeculationHint]:
        """
        基于最近的对话和文件访问模式, 预判下一步需求。

        返回一组预判提示, 引擎可据此预热缓存。
        """
        hints: list[SpeculationHint] = []
        self._file_access_history.extend(recent_files)

        # ── 策略 1: 文件关联预加载 ──
        for f in recent_files[-5:]:
            related = self._find_related_files(f)
            for rf in related:
                hints.append(SpeculationHint("file_preload", rf, confidence=0.6))

        # ── 策略 2: 对话模式识别 ──
        if recent_messages:
            last_msg = recent_messages[-1].get("content", "")
            if isinstance(last_msg, str):
                pattern_hints = self._detect_patterns(last_msg)
                hints.extend(pattern_hints)

        # ── 策略 3: 测试文件预测 ──
        for f in recent_files[-3:]:
            test_file = self._predict_test_file(f)
            if test_file:
                hints.append(SpeculationHint("file_preload", test_file, confidence=0.7))

        # 去重并按置信度排序
        seen = set()
        unique: list[SpeculationHint] = []
        for h in hints:
            if h.content not in seen:
                seen.add(h.content)
                unique.append(h)
        unique.sort(key=lambda x: x.confidence, reverse=True)

        return unique[:10]

    def _find_related_files(self, filepath: str) -> list[str]:
        """查找与给定文件相关的文件 (同目录、同模块)。"""
        path = Path(filepath)
        related: list[str] = []

        if path.exists():
            parent = path.parent
            # 同目录下的其他文件
            for sibling in parent.iterdir():
                if sibling.is_file() and sibling != path and sibling.suffix in (".py", ".ts", ".js", ".md"):
                    related.append(str(sibling))
                    if len(related) >= 3:
                        break

        return related

    def _detect_patterns(self, message: str) -> list[SpeculationHint]:
        """从对话内容中检测意图模式。"""
        hints: list[SpeculationHint] = []

        # "修复" 相关 → 可能需要查看日志
        if re.search(r"(修复|fix|bug|error|报错)", message, re.IGNORECASE):
            hints.append(SpeculationHint("next_action", "likely_debugging", confidence=0.7))

        # "测试" 相关 → 可能需要运行测试
        if re.search(r"(测试|test|验证|check)", message, re.IGNORECASE):
            hints.append(SpeculationHint("next_action", "likely_testing", confidence=0.7))

        # "部署" 相关 → 可能需要配置文件
        if re.search(r"(部署|deploy|上线|发布)", message, re.IGNORECASE):
            hints.append(SpeculationHint("next_action", "likely_deployment", confidence=0.6))

        return hints

    def _predict_test_file(self, filepath: str) -> Optional[str]:
        """预测与源文件对应的测试文件。"""
        path = Path(filepath)
        if path.suffix != ".py" or "test" in path.name:
            return None

        # 常见的测试文件命名模式
        candidates = [
            path.parent / f"test_{path.name}",
            path.parent / "tests" / f"test_{path.name}",
            path.parent.parent / "tests" / f"test_{path.name}",
        ]
        for c in candidates:
            if c.exists():
                return str(c)
        return None
