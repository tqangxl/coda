"""
Coda V7.2 — SkillForge: Autonomous Self-Evolution Engine
自主进化引擎: 遇到新任务 → 摸索 → 固化 → 写入记忆 → 下次直接调用。

进化四阶段:
  1. DETECT   — 任务前: 检测是否有可复用 Skill (技能检索)
  2. FORGE    — 任务后: LLM 从执行历史中提炼可复用路径
  3. SOLIDIFY — 写入 SKILL.md 文件 + wiki_nodes 记忆层
  4. RECALL   — 下次同类任务: 直接注入 Skill 上下文，跳过摸索阶段

设计原则:
  - 每个 Skill 必须有可验证的 trigger_patterns (触发词向量)
  - Skill 内容 = 最优执行路径 + 工具序列 + 已知坑点
  - 双写保障: 文件系统 (SKILL.md) + SurrealDB wiki_nodes 记忆层
  - 无幻觉: LLM 只提炼 messages 中实际发生的步骤，禁止凭空生成
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("Coda.skill_forge")


# ════════════════════════════════════════
#  Data Models
# ════════════════════════════════════════

@dataclass
class ForgeCandidate:
    """一个待固化的技能候选。"""
    task_summary: str                     # 任务一句话描述
    trigger_patterns: list[str]           # 触发关键词列表
    execution_steps: list[str]            # 提炼后的执行步骤
    tools_used: list[str]                 # 使用的工具名称
    known_pitfalls: list[str]             # 踩过的坑 (stagnation / error 节点)
    success_signal: str                   # 验证成功的信号
    confidence: float = 0.0              # LLM 对提炼质量的自评分 (0-1)

@dataclass
class SkillForgeResult:
    """固化结果报告。"""
    skill_name: str
    skill_path: str = ""
    wiki_node_id: str = ""
    success: bool = False
    reason: str = ""


@dataclass
class RecallResult:
    """技能检索结果。"""
    skill_name: str
    skill_content: str
    confidence: float     # 匹配置信度
    trigger_matched: str  # 命中的触发词


# ════════════════════════════════════════
#  SkillForge Engine
# ════════════════════════════════════════

class SkillForge:
    """
    自主技能进化引擎。

    用法:
        forge = SkillForge(llm=llm, skill_factory=skill_factory, db=db)

        # 任务完成后 (在 _perform_silent_ritual 之后调用)
        result = await forge.crystallize(
            task=user_message,
            messages=self._messages,
            modified_files=list(self.htas.modified_files),
        )

        # 任务开始前 (在意图分析之后调用)
        recall = await forge.recall(task=user_message)
        if recall:
            inject recall.skill_content into system prompt
    """

    def __init__(
        self,
        llm: Any,
        skill_factory: Any,          # SkillFactory instance
        db: Optional[Any] = None,    # SurrealStore instance (optional)
        target_skills_dir: Optional[Path] = None,
        project_id: str = "Coda_core",
    ):
        self.llm = llm
        self.skill_factory = skill_factory
        self.db = db
        self.target_skills_dir = target_skills_dir
        self.project_id = project_id
        self._forge_count = 0

    # ════════════════════════════════════════
    #  Phase 1: RECALL — 任务前技能检索
    # ════════════════════════════════════════

    async def recall(self, task: str, top_k: int = 1) -> Optional[RecallResult]:
        """
        任务开始前: 检索是否有可复用的 Skill。
        优先从 SurrealDB 语义检索，降级到关键词匹配。
        """
        # 1a. Semantic search via DB embedding
        if self.db and hasattr(self.db, '_safe_query'):
            try:
                result = await self._db_semantic_recall(task, top_k)
                if result:
                    logger.info(f"🎯 SkillForge RECALL hit: '{result.skill_name}' (conf={result.confidence:.2f})")
                    return result
            except Exception as e:
                logger.debug(f"DB recall failed, falling back to keyword: {e}")

        # 1b. Keyword fallback using SkillFactory registry
        result = self._keyword_recall(task)
        if result:
            logger.info(f"🎯 SkillForge RECALL (keyword): '{result.skill_name}' (conf={result.confidence:.2f})")
        return result

    async def _db_semantic_recall(self, task: str, top_k: int) -> Optional[RecallResult]:
        """SurrealDB 向量语义检索技能节点。"""
        # Embed the task query
        from .embedder import QwenEmbedder
        embedder = QwenEmbedder()
        vec = embedder.encode_single(task)
        if not vec:
            return None

        q = (
            "SELECT id, title, body, tags, "
            "  vector::similarity::cosine(embedding, $vec) AS sim "
            "FROM wiki_nodes "
            "WHERE project_id = $pid AND type = 'technique' AND status != 'archived' "
            "ORDER BY sim DESC LIMIT $k"
        )
        assert self.db is not None
        res = await self.db._safe_query(q, {"pid": self.project_id, "vec": vec, "k": top_k})
        rows = self.db._extract_result(res) or []

        for row in rows:
            sim = row.get("sim", 0)
            if sim < 0.70:
                continue
            title = row.get("title", "")
            body = row.get("body", "")
            tags = row.get("tags", [])
            return RecallResult(
                skill_name=title,
                skill_content=body,
                confidence=sim,
                trigger_matched=f"semantic:{sim:.2f}",
            )
        return None

    def _keyword_recall(self, task: str) -> Optional[RecallResult]:
        """关键词匹配 SkillFactory 注册表。"""
        task_lower = task.lower()
        best: Optional[tuple[float, Any]] = None

        for skill_def in self.skill_factory._registry.values():
            # Check description and name overlap
            desc_words = set(re.findall(r'\w+', skill_def.description.lower()))
            task_words = set(re.findall(r'\w+', task_lower))
            overlap = desc_words & task_words
            if not overlap:
                continue
            score = len(overlap) / max(len(task_words), 1)
            if best is None or score > best[0]:
                best = (score, skill_def)

        if best and best[0] >= 0.25:
            skill_def = best[1]
            content = self.skill_factory.inject_skill(skill_def.name) or ""
            matched_words = ", ".join(
                set(re.findall(r'\w+', skill_def.description.lower()))
                & set(re.findall(r'\w+', task_lower))
            )
            return RecallResult(
                skill_name=skill_def.name,
                skill_content=content,
                confidence=best[0],
                trigger_matched=f"keyword:{matched_words}",
            )
        return None

    # ════════════════════════════════════════
    #  Phase 2: FORGE — 从执行历史提炼
    # ════════════════════════════════════════

    async def crystallize(
        self,
        task: str,
        messages: list[dict[str, Any]],
        modified_files: list[str] | None = None,
        min_steps: int = 3,
    ) -> Optional[SkillForgeResult]:
        """
        任务完成后: 从 messages 历史中提炼可复用执行路径。
        只有当任务步骤数 >= min_steps 时才值得固化。
        """
        if len(messages) < min_steps * 2:
            logger.debug("SkillForge: too few messages, skipping crystallization")
            return None

        # Extract tool calls and assistant responses from history
        candidate = await self._llm_forge(task, messages, modified_files or [])
        if not candidate or candidate.confidence < 0.5:
            logger.debug(f"SkillForge: LLM confidence too low ({candidate.confidence if candidate else 0:.2f}), skipping")
            return None

        return await self._solidify(candidate)

    async def _llm_forge(
        self,
        task: str,
        messages: list[dict[str, Any]],
        modified_files: list[str],
    ) -> Optional[ForgeCandidate]:
        """
        调用 LLM 从对话历史中提炼技能蓝图。
        严格要求: 只提炼实际发生的步骤，禁止幻觉。
        """
        # Compress history to fit context
        history_summary = self._compress_history(messages)

        prompt = f"""你是一个技能提炼专家。分析以下任务执行记录，提炼出一个可复用的技能蓝图。

规则:
1. 只提炼历史中实际发生的步骤，严禁凭空生成
2. 如果执行路径不稳定或充满错误重试，confidence 应低于 0.4
3. trigger_patterns 应是会触发相同任务的关键词组合

任务: {task}
修改的文件: {', '.join(modified_files) if modified_files else '无'}

执行历史摘要:
{history_summary[:3000]}

请返回严格的 JSON (无 markdown):
{{
  "task_summary": "一句话描述此技能做什么",
  "trigger_patterns": ["关键词1", "关键词2", "..."],
  "execution_steps": ["步骤1", "步骤2", "..."],
  "tools_used": ["工具名1", "工具名2"],
  "known_pitfalls": ["坑点1", "..."],
  "success_signal": "什么标志着任务成功",
  "confidence": 0.0
}}"""

        try:
            response = await self.llm.call([{"role": "user", "content": prompt}])
            json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if not json_match:
                return None
            data = json.loads(json_match.group(0))
            return ForgeCandidate(
                task_summary=data.get("task_summary", task[:80]),
                trigger_patterns=data.get("trigger_patterns", []),
                execution_steps=data.get("execution_steps", []),
                tools_used=data.get("tools_used", []),
                known_pitfalls=data.get("known_pitfalls", []),
                success_signal=data.get("success_signal", ""),
                confidence=float(data.get("confidence", 0)),
            )
        except Exception as e:
            logger.error(f"SkillForge LLM forge failed: {e}")
            return None

    # ════════════════════════════════════════
    #  Phase 3: SOLIDIFY — 双写固化
    # ════════════════════════════════════════

    async def _solidify(self, candidate: ForgeCandidate) -> SkillForgeResult:
        """双写固化: SKILL.md 文件系统 + SurrealDB wiki_nodes 记忆层。"""
        self._forge_count += 1
        skill_name = self._slugify(candidate.task_summary)
        result = SkillForgeResult(skill_name=skill_name)

        # Build SKILL.md content
        skill_content = self._build_skill_md(candidate)

        # 3a. Write SKILL.md to filesystem
        try:
            path = self.skill_factory.skillify(
                skill_name=skill_name,
                description=candidate.task_summary,
                content=skill_content,
                target_dir=self.target_skills_dir,
            )
            result.skill_path = str(path)
            logger.info(f"🧬 SkillForge: Written to {path}")
        except Exception as e:
            logger.error(f"SkillForge file write failed: {e}")
            result.reason = str(e)

        # 3b. Write to SurrealDB wiki_nodes memory layer
        if self.db:
            try:
                node_id = f"skill-{skill_name}-{uuid.uuid4().hex[:6]}"
                node_data = {
                    "id": node_id,
                    "title": f"[SKILL] {candidate.task_summary}",
                    "body": skill_content,
                    "type": "technique",
                    "status": "validated",
                    "project_id": self.project_id,
                    "layer": 3,
                    "memory_horizon": "long_term",
                    "confidence": candidate.confidence,
                    "activation_score": 5.0,
                    "tags": candidate.trigger_patterns[:10],
                    "source_format": "md",
                    "created_at": time.time(),
                    "updated_at": time.time(),
                }
                await self.db.upsert_knowledge_node(node_data)
                result.wiki_node_id = node_id
                logger.info(f"🧬 SkillForge: wiki_node '{node_id}' written to memory layer")
            except Exception as e:
                logger.warning(f"SkillForge DB write failed (non-fatal): {e}")

        result.success = bool(result.skill_path or result.wiki_node_id)
        if result.success:
            logger.info(
                f"✅ SkillForge crystallized: '{skill_name}' "
                f"(conf={candidate.confidence:.2f}, steps={len(candidate.execution_steps)})"
            )
        return result

    # ════════════════════════════════════════
    #  Helpers
    # ════════════════════════════════════════

    @staticmethod
    def _build_skill_md(c: ForgeCandidate) -> str:
        """构建 SKILL.md 正文内容。"""
        lines = [
            f"# {c.task_summary}",
            "",
            f"**触发条件**: {', '.join(c.trigger_patterns)}",
            f"**成功信号**: {c.success_signal}",
            f"**置信度**: {c.confidence:.0%}",
            "",
            "## 执行步骤",
        ]
        for i, step in enumerate(c.execution_steps, 1):
            lines.append(f"{i}. {step}")

        if c.tools_used:
            lines += ["", "## 工具序列", ", ".join(c.tools_used)]

        if c.known_pitfalls:
            lines += ["", "## 已知坑点"]
            for pit in c.known_pitfalls:
                lines.append(f"- ⚠️ {pit}")

        return "\n".join(lines)

    @staticmethod
    def _slugify(text: str) -> str:
        """将文本转为 slug 形式的技能名。"""
        slug = re.sub(r'[^\w\s-]', '', text.lower())
        slug = re.sub(r'[\s_-]+', '-', slug).strip('-')
        return slug[:48] or f"skill-{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _compress_history(messages: list[dict[str, Any]]) -> str:
        """压缩对话历史为可读摘要 (保留工具调用和关键决策)。"""
        lines = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if not content:
                continue
            # Keep tool calls and assistant messages, skip long user turns
            if role == "assistant":
                lines.append(f"[Assistant]: {str(content)[:400]}")
            elif role == "tool":
                lines.append(f"[ToolResult]: {str(content)[:200]}")
            elif role == "user" and len(lines) < 3:
                lines.append(f"[User]: {str(content)[:200]}")
        return "\n".join(lines[-40:])  # Last 40 turns only
