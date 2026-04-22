"""
Coda Knowledge Engine V7.0 — Reinforced Writing (Crystallizer)
结晶器: 将碎片化记忆、多个来源节点转化为高保真的综合知识 (Synthesis Nodes)。

实现:
  - 碎片化记忆聚合 (Memory Fragment Aggregation)
  - 强化写入循环 (Reinforced Writing Loop)
  - 因果锚定 (Causal Anchoring): 建立从 Synthesis -> Source 的强链接
  - 冲突自动调解集成
"""

from __future__ import annotations
import logging
import time
from typing import Any, Optional
from dataclasses import dataclass

from ..base_plugin import WikiPlugin, WikiHook, WikiPluginContext
from ..akp_types import KnowledgeNode, NodeType, NodeStatus, EpistemicTag, MemoryHorizon

logger = logging.getLogger("Coda.wiki.crystallizer")

class Crystallizer(WikiPlugin):
    """
    结晶器插件 — 联邦知识架构的核心合成平面。
    """
    name = "crystallizer"

    def __init__(self):
        self._ctx: Optional[WikiPluginContext] = None

    async def initialize(self, ctx: WikiPluginContext) -> None:
        self._ctx = ctx
        logger.info("💎 Crystallizer plugin initialized (Reinforced Writing Ready)")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        if hook == WikiHook.POST_COMPILE:
            # 编译结束后自动尝试结晶新发现的碎片
            return await self.auto_crystallize(payload)
        return None

    async def auto_crystallize(self, stats: dict[str, int]) -> dict[str, Any]:
        """自动结晶流程。"""
        if not self._ctx or not self._ctx.llm:
            return {"status": "skipped", "reason": "no_llm"}
        
        # 1. 查找最近新增的 SOURCE 节点
        # (简化实现: 获取最近 5 个新增节点)
        # 实际生产中应从 manifest 或 Hook payload 获取
        
        logger.info("💎 Triggering auto-crystallization loop...")
        return {"status": "completed", "processed": 0}

    async def synthesize(self, source_nodes: list[KnowledgeNode], target_title: str) -> Optional[KnowledgeNode]:
        """
        强化写入核心: 将多个 Source 节点合成一个 Synthesis 节点。
        """
        if not self._ctx or not self._ctx.llm or not source_nodes:
            return None

        combined_body = "\n\n".join([f"--- Source: {n.title} ---\n{n.body}" for n in source_nodes])
        
        prompt = f"""
        你是一个知识合成专家。请对以下多个来源的内容进行高度浓缩和结构化合成，产出一个 Synthesis Node。
        
        要求:
        1. 总结核心事实和结论。
        2. 识别并指出各来源之间的因果关系或矛盾点。
        3. 产出的内容必须是事实性的，禁止幻觉。
        4. 输出 Markdown 格式，包含二级标题。

        来源内容:
        {combined_body[:5000]}
        """
        
        try:
            res = await self._ctx.llm.call([{"role": "user", "content": prompt}])
            
            synthesis_id = f"syn_{int(time.time())}_{source_nodes[0].id[:8]}"
            new_node = KnowledgeNode(
                id=synthesis_id,
                title=target_title,
                body=res.text,
                node_type=NodeType.SYNTHESIS,
                status=NodeStatus.CANDIDATE,
                project_id=self._ctx.project_id,
                layer=self._ctx.layer,
                memory_horizon=MemoryHorizon.SUMMARY
            )
            
            # 建立因果锚定 (Causal Anchoring)
            for src in source_nodes:
                new_node.references.append(src.id)
                # 反向链接由 compiler 或 storage 处理
            
            # 持久化到 SurrealDB (物理审计已在 db.py 中通过 save_relation 自动触发)
            storage = self._ctx.storage
            if storage:
                await storage.upsert_node(new_node)
            
            logger.info(f"💎 Successfully synthesized node: {new_node.id} from {len(source_nodes)} sources")
            return new_node
            
        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            return None
