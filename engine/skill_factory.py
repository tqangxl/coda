"""
Coda V4.0 — Skill Factory & Self-Evolution Protocol (Pillar 13)
自进化协议: 成功案例自动固化为 SKILL.md, 实现大脑能力的物理增长。

设计参考: Claude Code 原始 TS `skills/loadSkillsDir.ts`, `skillify.ts`

进化逻辑链:
  1. 反思 (Reflection): 任务成功后, Agent 回顾整个会话历史
  2. 提取 (Synthesis): 总结工具组合、绕坑技巧、最有效指令
  3. 固化 (Persistence): 调用 FileWriteTool, 写入 skills/ 目录
  4. 注册 (Activation): resolve_skill_path 实时扫描, 下次启动即可用
"""

from __future__ import annotations

import logging
import os
import re
import yaml
from pathlib import Path
from typing import Optional, Any, Sequence

logger = logging.getLogger("Coda.skills")

# 单文件 Skill 内容限制 (字符)
SKILL_CHAR_LIMIT = 4000
# 全部 Skill 总预算
TOTAL_SKILL_BUDGET = 12000


class SkillDefinition:
    """一个已加载的 Skill 定义。"""

    def __init__(self, name: str, description: str, content: str, path: Path):
        self.name = name
        self.description = description
        self.content = content[:SKILL_CHAR_LIMIT]  # 强制截断
        self.path = path
        self.char_count = len(self.content)
        self.assets: list[Path] = [] # [V5.2] 关联资产 (scripts/, templates/)

    def __repr__(self) -> str:
        return f"Skill({self.name}, {self.char_count} chars)"


class SkillFactory:
    """
    动态技能工厂。

    负责:
    1. 递归扫描 skills/ 目录, 热加载所有 SKILL.md
    2. 按需向 Agent 注入专家指令 (单文件 4000 字符限制)
    3. 提供 skillify 接口, 让 Agent 自己生成新技能
    """

    def __init__(self, skills_dirs: Sequence[str | Path]):
        self.skills_dirs = [Path(d) for d in skills_dirs]
        self._registry: dict[str, SkillDefinition] = {}
        self._scan()

    def _scan(self) -> None:
        """递归扫描所有技能目录, 加载 SKILL.md。"""
        for skills_dir in self.skills_dirs:
            if not skills_dir.exists():
                continue
            # 搜索所有 SKILL.md
            for skill_file in skills_dir.rglob("SKILL.md"):
                try:
                    self._load_skill(skill_file)
                except Exception as e:
                    logger.warning(f"Failed to load skill {skill_file}: {e}")

        logger.info(f"Loaded {len(self._registry)} skills: {list(self._registry.keys())}")

    def _load_skill(self, path: Path) -> None:
        """解析 SKILL.md 文件, 提取 frontmatter 与内容。"""
        raw = path.read_text(encoding="utf-8", errors="replace")

        # 解析 YAML frontmatter
        name = path.parent.name
        description = ""

        frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", raw, re.DOTALL)
        if frontmatter_match:
            try:
                meta = yaml.safe_load(frontmatter_match.group(1))
                if isinstance(meta, dict):
                    name = meta.get("name", name)
                    description = meta.get("description", "")
                    if isinstance(description, str):
                        description = description.strip()
            except yaml.YAMLError:
                pass
            content = raw[frontmatter_match.end():]
        else:
            content = raw

        # 截取描述 (第一行非空行)
        if not description:
            for line in content.split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    description = line[:200]
                    break

        skill = SkillDefinition(
            name=name,
            description=description,
            content=content,
            path=path,
        )
        
        # [V5.2] 扫描关联资产 (同目录下除 SKILL.md 外的文件)
        skill_dir = path.parent
        for asset in skill_dir.rglob("*"):
            if asset.is_file() and asset.name != "SKILL.md":
                skill.assets.append(asset)
        
        self._registry[name] = skill

    def get_skill(self, name: str) -> Optional[SkillDefinition]:
        """按名称获取技能。"""
        return self._registry.get(name)

    def list_skills(self) -> list[dict[str, Any]]:
        """列出所有可用技能 (名称 + 描述)。"""
        return [
            {"name": s.name, "description": s.description, "chars": s.char_count}
            for s in self._registry.values()
        ]

    def inject_skill(self, name: str) -> Optional[str]:
        """
        将指定 Skill 的内容注入到 Agent 上下文中。

        返回格式化后的 Skill 内容, 或 None。
        遵守 4000 字符限制。
        """
        skill = self.get_skill(name)
        if not skill:
            return None

        asset_lines = []
        if skill.assets:
            asset_lines.append("\n  <assets>")
            for asset in skill.assets:
                rel_path = asset.relative_to(skill.path.parent)
                asset_lines.append(f"    - {rel_path}")
            asset_lines.append("  </assets>")
            
        return (
            f"<skill name=\"{skill.name}\">\n"
            f"{skill.content}"
            f"{''.join(asset_lines)}\n"
            f"</skill>"
        )

    def skillify(
        self,
        skill_name: str,
        description: str,
        content: str,
        target_dir: Optional[Path] = None,
    ) -> Path:
        """
        自进化协议 (The Skillify Protocol)。

        由 Agent 调用: 将成功经验固化为新的 SKILL.md。

        流程:
        1. 创建 skills/{skill_name}/ 目录
        2. 写入 SKILL.md (带 YAML frontmatter)
        3. 自动注册到 Registry
        """
        if target_dir is None:
            target_dir = self.skills_dirs[0] if self.skills_dirs else Path("skills")

        skill_dir = target_dir / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)

        skill_file = skill_dir / "SKILL.md"

        # 构建 SKILL.md
        frontmatter = yaml.dump({
            "name": skill_name,
            "description": description,
        }, default_flow_style=False, allow_unicode=True)

        full_content = f"---\n{frontmatter}---\n\n{content[:SKILL_CHAR_LIMIT]}"
        skill_file.write_text(full_content, encoding="utf-8")

        # 自动注册
        self._load_skill(skill_file)

        logger.info(f"🧬 Skillified: {skill_name} → {skill_file}")
        return skill_file

    def reload(self) -> None:
        """热重载所有技能。"""
        self._registry.clear()
        self._scan()
