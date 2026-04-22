import re
import logging
import time
from pathlib import Path
from typing import Any, Callable, Protocol

logger = logging.getLogger("Coda.history")

# [Hermes Pattern] Context Tiering 阈值 (Pillar 23)
COMPACTION_THRESHOLD = 40_000   # 触发压缩的 Token 数 (大约 30k 字符)
TARGET_ACTIVE_TOKENS = 15_000   # 压缩后保留的活跃 Token 数
MAX_SUMMARY_CHAR_LIMIT = 5000   # 摘要的最大字符数，防止摘要本身膨胀

class HistoryCompactor:
    _last_summary: str
    """
    Coda 多层次上下文管理 (Context Tiering)。
    实现 Pillar 5 (自压缩) 与 Pillar 23 (上下文管理)。
    """

    def __init__(self, threshold: int = COMPACTION_THRESHOLD, target: int = TARGET_ACTIVE_TOKENS) -> None:
        self.threshold = threshold
        self.target = target
        self._last_summary = ""

    def needs_compaction(self, messages: list[dict[str, object]], current_usage: int = 0) -> bool:
        """检查是否需要压缩。如果传入了 current_usage (精准值)，优先使用。"""
        if current_usage > 0:
            return current_usage > self.threshold
        
        # 否则使用估算值
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        estimated_tokens = total_chars // 3
        return estimated_tokens > self.threshold

    def compact(self, messages: list[dict[str, object]], complexity: str = "simple", memory: object | None = None, model_call: Callable[..., object] | None = None) -> list[dict[str, object]]:
        """
        执行多层级上下文压缩 (Context Tiering)。
        
        分级策略:
        - Tier 1: Pinned (System Message) -> 100% 保留
        - Tier 2: Active (Recent 10 messages) -> 100% 保留
        - Tier 3: Summary (Recursive summarized history) -> 动态递归更新
        - Tier 4: Archive (Old messages) -> 提炼后从内存移除
        """
        if len(messages) <= 6:
            return messages

        # 1. 分离消息
        system_msgs = [m for m in messages if m.get("role") == "system"]
        active_msgs = messages[-10:]  # 保留最近 10 条作为活跃上下文
        
        # 排除掉 system 和 active 后的旧消息
        archived_candidates = [m for m in messages if m not in system_msgs and m not in active_msgs]
        
        if not archived_candidates:
            return messages

        # 2. 递归总结 (Recursive Summarization)
        # 如果旧消息中已经包含之前的 summary，我们需要将其整合
        prev_summaries = []
        new_to_summarize = []
        
        for m in archived_candidates:
            content = str(m.get("content", ""))
            if "<conversation_summary>" in content:
                prev_summaries.append(content)
            else:
                new_to_summarize.append(m)

        # 3. 提取新知识点 (Rule-based 降级提取)
        new_insights = self._extract_robust_summary(new_to_summarize)
        
        # 将被丢弃的上下文信息存入长效记忆库 (Tier 4 Archive 归档)
        if memory and hasattr(memory, "remember"):
            getattr(memory, "remember")(content=f"[历史归档]\n{new_insights}", category="archive", importance=0.8)
        
        # 4. 合并摘要
        full_summary = ""
        if prev_summaries:
            # 简单合并上一次的总结
            last_sum = prev_summaries[-1]
            # 提取标签内的内容
            match = re.search(r"<conversation_summary>(.*?)</conversation_summary>", last_sum, re.DOTALL)
            if match:
                full_summary = f"{match.group(1).strip()}\n\n--- 进度更新 ---\n{new_insights}"
            else:
                full_summary = f"{last_sum}\n\n{new_insights}"
        else:
            full_summary = new_insights

        # 限制摘要长度，根据阶段重度和任务复杂度放开限制 (Pillar 28 自适应分级)
        limit = MAX_SUMMARY_CHAR_LIMIT
        if complexity == "complex":
            limit = 9000
        elif complexity == "extreme":
            limit = 15000

        if len(full_summary) > limit:
            full_summary = full_summary[:1000] + "... [中略] ..." + full_summary[-(limit-1000):]

        self._last_summary = full_summary

        # 5. 构建压缩后的新历史
        compacted = list(system_msgs)
        compacted.append({
            "role": "user",
            "content": f"<conversation_summary>\n{full_summary}\n</conversation_summary>\n\n"
                       f"(注：以上是前述 {len(archived_candidates)} 条对话的压缩摘要，保留了关键决策和已完成任务。请基于此继续当前任务。)"
        })
        compacted.extend(active_msgs)

        logger.info(f"✨ Context Tiering: {len(messages)} -> {len(compacted)} messages. Memory freed.")
        return compacted

    def export_session_summary(self, messages: list[dict[str, Any]]) -> str:
        """
        [V5.1] 提炼本轮会话的最终物理摘要，用于 Git Commit。
        
        返回格式化的精简概要，包含操作的文件清单和关键决策。
        """
        raw_summary = self._extract_robust_summary(messages)
        
        # 提取首行作为 Commit 标题
        achievement = "Task completed successfully"
        file_count = raw_summary.count('`') // 2
        if file_count > 0:
            achievement = f"Autonomous implementation completed (Modified {file_count} files)"
            
        return f"{achievement}\n\n{raw_summary}"

    def _extract_robust_summary(self, messages: list[dict[str, Any]]) -> str:
        """
        鲁棒性提取引擎：真实地从原始 Token 流中提取因果、决策与文件状态。
        """
        files_modified = set()
        tools_called = set()
        key_decisions = []
        errors_resolved = []

        for m in messages:
            role = str(m.get("role", "")).lower()
            content = str(m.get("content", ""))
            
            # 1. 深度检测文件操作 (Pillar 2)
            if "TargetFile" in content:
                match = re.search(r"TargetFile[:\"'\s]+([A-Za-z]:\\[^\s\"',]+|/[^\s\"',]+)", content)
                if match:
                    files_modified.add(match.group(1))

            # 2. 剪枝工具输出 (Pillar 23)
            # 如果是工具结果且过长，我们只记录概要而非全量数据
            if role in ("tool", "function"):
                tool_name = m.get("name", "unknown_tool")
                tools_called.add(tool_name)
                if len(content) > 500:
                    content_summary = f"({tool_name} output omitted, size={len(content)} chars)"
                else:
                    content_summary = content
            
            # 3. 提取关键指令/决策
            if role == "user" and len(content) < 500:
                key_decisions.append(f"长官要求：{content.strip()}")
            
            if role in ("assistant", "model") and len(content) > 20:
                # 尝试从思考片段提取
                thought_match = re.search(r"<thought>(.*?)</thought>", content, re.DOTALL)
                if thought_match:
                    key_decisions.append(f"引擎决策：{thought_match.group(1)[:150]}...")

        # 构建结构化 Markdown 摘要
        lines = ["### 核心上下文回放"]
        if files_modified:
            lines.append(f"**操作的文件**: {', '.join([f'`{Path(f).name}`' for f in files_modified])}")
        
        if tools_called:
            lines.append(f"**调用的工具**: {', '.join(tools_called)}")
            
        if key_decisions:
            lines.append("**关键路径记录**:")
            for d in key_decisions[-10:]:
                lines.append(f"- {d}")

        return "\n".join(lines)
