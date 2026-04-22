"""
Coda V4.0 — Global Session Memory & Team Memory (Pillar 17 & 19)
跨越维度的长效记忆: 自动提取精华, 使 Agent 越用越懂你。

设计参考:
  - 原始 TS `services/SessionMemory/sessionMemory.ts`
  - 原始 TS `memdir/findRelevantMemories.ts`, `teamMemPaths.ts`
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Sequence, Mapping
from pathlib import Path
from typing import Any, cast, TYPE_CHECKING, Protocol, runtime_checkable, override
if TYPE_CHECKING:
    from .db import SurrealStore

logger = logging.getLogger("Coda.memory")


class MemoryEntry:
    """一条记忆单元。"""
    content: str
    category: str
    source_session: str
    importance: float
    created_at: float
    access_count: int
    last_accessed: float

    def __init__(
        self,
        content: str,
        category: str = "general",
        source_session: str = "",
        importance: float = 0.5,
    ):
        self.content = content
        self.category = category  # coding_style, debug_pattern, api_quirk, etc.
        self.source_session = source_session
        self.importance = importance
        self.created_at = time.time()
        self.access_count = 0
        self.last_accessed = time.time()

    def to_dict(self) -> dict[str, object]:
        return {
            "content": self.content,
            "category": self.category,
            "source_session": self.source_session,
            "importance": self.importance,
            "created_at": self.created_at,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "MemoryEntry":
        entry = cls(
            content=str(data.get("content", "")),
            category=str(data.get("category", "general")),
            source_session=str(data.get("source_session", "")),
            importance=float(cast(Any, data.get("importance", 0.5))),
        )
        entry.created_at = float(cast(Any, data.get("created_at", time.time())))
        entry.access_count = int(cast(Any, data.get("access_count", 0)))
        entry.last_accessed = float(cast(Any, data.get("last_accessed", time.time())))
        return entry


class SessionMemory:
    """
    跨 Session 的长效记忆服务 (Pillar 17)。

    自动提取跨 Session 的精华知识:
    - 长官的编码风格偏好
    - 特定服务器的配置怪癖
    - 常用的 Debug 逻辑
    - API 报错的解决方案

    使 Agent 越用越像长官的分身。
    """

    def __init__(self, memory_dir: str | Path):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self._memories: list[MemoryEntry] = []
        self._load()

    def _load(self) -> None:
        """从磁盘加载所有记忆。"""
        memory_file = self.memory_dir / "session_memories.json"
        if memory_file.exists():
            try:
                data = json.loads(memory_file.read_text(encoding="utf-8"))
                self._memories = [MemoryEntry.from_dict(cast(dict[str, object], d)) for d in data]
                logger.info(f"Loaded {len(self._memories)} memories")
            except Exception as e:
                logger.warning(f"Failed to load memories: {e}")

    def save(self) -> None:
        """持久化所有记忆到磁盘。"""
        memory_file = self.memory_dir / "session_memories.json"
        data = [m.to_dict() for m in self._memories]
        memory_file.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def remember(self, content: str, category: str = "general", importance: float = 0.5) -> None:
        """存入一条新记忆。"""
        entry = MemoryEntry(content=content, category=category, importance=importance)
        self._memories.append(entry)
        # 限制总量
        if len(self._memories) > 1000:
            self._memories = self._prune()
        self.save()

    def recall(self, query: str, top_k: int = 5) -> list[MemoryEntry]:
        """
        语义化记忆搜索 (Pillar 26: Agentic Session Search)。

        使用关键词匹配 (未来可接入向量检索)。
        Agent 在遇到难题时, 通过检索自主查询历史中的成功案例。
        """
        query_lower = query.lower()
        scored: list[tuple[float, MemoryEntry]] = []

        for mem in self._memories:
            # 简单的关键词匹配打分
            content_lower = mem.content.lower()
            score = 0.0
            for word in query_lower.split():
                if word in content_lower:
                    score += 1.0
            # 加权: 重要性 + 新鲜度
            score *= mem.importance
            score *= 1.0 / (1.0 + (time.time() - mem.last_accessed) / 86400)  # 按天衰减

            if score > 0:
                mem.access_count += 1
                mem.last_accessed = time.time()
                scored.append((score, mem))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:top_k]]

    def extract_insights(self, conversation: Sequence[Mapping[str, object]]) -> list[str]:
        """
        从完成的对话中提取可持久化的知识 (用于自动学习)。

        分析维度:
        - 用户偏好模式 (如: 喜欢用特定的编码风格)
        - 成功的问题解决路径
        - 值得记忆的 API 怪癖
        """
        insights: list[str] = []

        for msg in conversation:
            content_raw = msg.get("content", "")
            content = ""
            if isinstance(content_raw, list):
                content = " ".join(
                    str(cast(dict[str, object], p).get("text", "")) for p in content_raw if isinstance(p, dict)
                )
            else:
                content = str(content_raw)

            # 检测用户偏好
            role = str(msg.get("role", ""))
            if role == "user" and len(content) > 50:
                # 简单的模式检测
                if "我喜欢" in content or "我习惯" in content or "请用" in content:
                    insights.append(f"[用户偏好] {content[:200]}")

            # 检测成功解决方案
            if role == "model" and ("成功" in content or "已修复" in content):
                insights.append(f"[解决方案] {content[:200]}")

        return insights

    def _prune(self) -> list[MemoryEntry]:
        """修剪低价值记忆, 保留精华。"""
        # 按重要性 × 访问频率排序, 保留前 500
        scored = sorted(
            self._memories,
            key=lambda m: m.importance * (m.access_count + 1),
            reverse=True,
        )
        return scored[:500]


class TeamMemory:
    """
    团队级记忆共享 (Pillar 19)。

    实现跨 Agent 实例的知识共享:
    一个 Agent 踩过的坑, 整个集群都不会再踩第二次。
    """

    def __init__(self, team_dir: str | Path):
        self.team_dir = Path(team_dir)
        self.team_dir.mkdir(parents=True, exist_ok=True)

    def share(self, agent_id: str, content: str, category: str = "tip") -> None:
        """将知识分享到团队记忆池。"""
        team_file = self.team_dir / f"{category}.jsonl"
        entry = {
            "agent_id": agent_id,
            "content": content,
            "category": category,
            "timestamp": time.time(),
        }
        with open(team_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def search(self, query: str, top_k: int = 5) -> list[dict[str, object]]:
        """在团队记忆池中搜索相关知识。"""
        query_lower = query.lower()
        results: list[tuple[float, dict[str, object]]] = []

        for jsonl_file in self.team_dir.glob("*.jsonl"):
            try:
                for line in jsonl_file.read_text(encoding="utf-8").strip().split("\n"):
                    if not line:
                        continue
                    entry = json.loads(line)
                    content_lower = entry.get("content", "").lower()
                    score = sum(1 for w in query_lower.split() if w in content_lower)
                    if score > 0:
                        results.append((score, entry))
            except Exception:
                continue

        results.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in results[:top_k]]


class CausalTriplet:
    """因果三元组: 描述 [动作] -> [后果] -> [补救] 的逻辑闭环。"""
    trigger: str
    action: str
    outcome: str
    confidence: float
    timestamp: float

    def __init__(
        self,
        trigger: str,      # 触发场景 (如 "pip install x failed")
        action: str,       # 尝试的动作 (如 "use --pre flag")
        outcome: str,      # 结果 (如 "success")
        confidence: float = 1.0,
    ):
        self.trigger = trigger
        self.action = action
        self.outcome = outcome
        self.confidence = confidence
        self.timestamp = time.time()

    def to_dict(self) -> dict[str, object]:
        return {
            "trigger": self.trigger,
            "action": self.action,
            "outcome": self.outcome,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
        }


class CausalGraph:
    """
    [Hermes Pattern] 因果推理图谱。
    存储从历史中学习到的路径依赖, 避免 Agent 重复同样的错误。
    """

    def __init__(self, db: SurrealStore | None = None):
        self.db: SurrealStore | None = db
        self._local_cache: list[CausalTriplet] = []

    def add_link(self, trigger: str, action: str, outcome: str):
        """记录一条因果路径。"""
        triplet = CausalTriplet(trigger, action, outcome)
        self._local_cache.append(triplet)
        
        if self.db:
             # 异步存入数据库
             try:
                 import asyncio
                 asyncio.create_task(self.db.save_causal_link(triplet.to_dict()))
             except Exception as e:
                 logger.debug(f"Failed to persist causal link: {e}")

    def suggest(self, trigger_query: str) -> str | None:
        """根据场景推荐最优动作。"""
        # 简单匹配策略
        for triplet in reversed(self._local_cache):
            if trigger_query.lower() in triplet.trigger.lower() and triplet.outcome == "success":
                return triplet.action
        return None

    def extract_from_history(self, history: list[dict[str, object]]) -> list[CausalTriplet]:
        """
        从工具执行失败-重试的历史中自动提取因果。
        [Pattern]: Tool Error -> Thought -> Next Tool Success.
        """
        extracted = []
        for i in range(len(history) - 2):
            m1 = history[i]   # Tool/Model result (Expected: Error)
            m2 = history[i+1] # Agent Reaction/Action
            m3 = history[i+2] # Outcome (Expected: Success)
            
            # 容错性检查: 处理不同平台的 role 命名 (Pillar 15)
            r1 = str(m1.get("role", "")).lower()
            r3 = str(m3.get("role", "")).lower()
            
            # 检测 [失败] -> [尝试] -> [成功] 序列
            # [Pillar 15/8] Support JSON-wrapped tool results
            m1_content = str(m1.get("content", "")).lower()
            m3_content = str(m3.get("content", "")).lower()
            
            is_m1_fail = "error" in m1_content
            is_m3_success = "error" not in m3_content
            
            if any(x in r1 for x in ("tool", "assistant", "model")) and is_m1_fail:
                if any(x in r3 for x in ("tool", "assistant", "model")) and is_m3_success:
                    # 命中成功修复路径 (Causal Triplet)
                    trigger = str(m1.get("content", ""))[:300].strip()
                    action = str(m2.get("content", ""))[:300].strip()
                    
                    if trigger and action:
                        triplet = CausalTriplet(trigger, action, "success")
                        extracted.append(triplet)
                        self.add_link(trigger, action, "success")
        return extracted
