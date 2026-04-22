"""
Coda V4.0 — Output Styles (低重要度 #15)
可定制输出风格: 让 Agent 的输出不再千篇一律。

设计参考: 原始 TS `services/OutputStyles/loadOutputStylesDir.ts`
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("Coda.styles")


class OutputStyle:
    """一个输出风格定义。"""
    def __init__(self, name: str, instruction: str, example: str = ""):
        self.name = name
        self.instruction = instruction
        self.example = example

    def to_prompt(self) -> str:
        """转换为 System Prompt 注入格式。"""
        s = f"<output_style name=\"{self.name}\">\n{self.instruction}\n"
        if self.example:
            s += f"<example>\n{self.example}\n</example>\n"
        s += "</output_style>"
        return s


# 内置风格
BUILTIN_STYLES: dict[str, OutputStyle] = {
    "concise": OutputStyle(
        "concise",
        "回答要极度简洁。能用一句话就不用两句。不要重复用户的问题。不用写总结段。",
    ),
    "detailed": OutputStyle(
        "detailed",
        "提供详尽的分析和解释。包含代码示例、边界情况讨论和替代方案。",
    ),
    "教官": OutputStyle(
        "教官",
        "你是一个严厉的教官。用军事化的口吻回答, 直接、果断、无废话。称呼用户为'长官'。",
        "报告长官！任务已完成。文件已写入，共 42 行，零报错。请求下一步指示！",
    ),
    "professor": OutputStyle(
        "professor",
        "以大学教授的风格回答。先解释原理, 再给出实操步骤, 最后留一个思考题。",
    ),
    "debug": OutputStyle(
        "debug",
        "输出必须包含完整的调试信息: 文件路径、行号、变量值、调用栈追踪。像 IDE 的调试面板一样。",
    ),
}


class StyleManager:
    """
    输出风格管理器。

    负责:
    1. 加载内置和自定义风格
    2. 按名称激活风格
    3. 将风格注入到 System Prompt
    """

    def __init__(self, styles_dir: Optional[str | Path] = None):
        self._styles: dict[str, OutputStyle] = dict(BUILTIN_STYLES)
        if styles_dir:
            self._load_custom(Path(styles_dir))

    def get(self, name: str) -> Optional[OutputStyle]:
        return self._styles.get(name)

    def list_styles(self) -> list[str]:
        return list(self._styles.keys())

    def add(self, style: OutputStyle) -> None:
        self._styles[style.name] = style

    def inject(self, name: str) -> Optional[str]:
        """将指定风格转换为 Prompt 注入字符串。"""
        style = self.get(name)
        return style.to_prompt() if style else None

    def _load_custom(self, styles_dir: Path) -> None:
        if not styles_dir.exists():
            return
        for f in styles_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                self._styles[data["name"]] = OutputStyle(
                    name=data["name"],
                    instruction=data.get("instruction", ""),
                    example=data.get("example", ""),
                )
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to load custom style from {f}: {e}")
