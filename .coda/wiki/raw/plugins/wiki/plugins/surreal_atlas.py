"""
Coda Knowledge Engine V6.5 — SurrealDB Atlas Bridge.
实现了 Wiki 知识图谱向 SurrealDB 全局存储的同步逻辑。
"""

from __future__ import annotations
import logging
from typing import Any, TYPE_CHECKING
from ..base_plugin import WikiPlugin, WikiHook, WikiPluginContext
from engine.db import SurrealStore

if TYPE_CHECKING:
    from ..akp_types import KnowledgeNode, KnowledgeRelation

logger = logging.getLogger("Coda.wiki.surreal_atlas")

class SurrealAtlasIndex(WikiPlugin):
    """
    SurrealDB 知识同步插件。
    将本地 SQLite 中的增量更新实时同步到全局 SurrealDB。
    """
    name = "surreal_atlas"

    def __init__(self):
        self._db: SurrealStore | None = None
        self._ctx: WikiPluginContext | None = None

    async def initialize(self, ctx: WikiPluginContext) -> None:
        self._ctx = ctx
        # 获取全局 DB 实例 (通常由引擎在初始化时注入到 context 或通过单例获取)
        # 这里我们直接创建一个，或者尝试从宿主引擎获取
        from engine.db import SurrealStore
        self._db = SurrealStore()
        connected = await self._db.connect()
        if not connected:
            logger.warning("⚠️ SurrealDB not connected, SurrealAtlas will be disabled (fallback to local SQLite only)")
        else:
            logger.info("✅ SurrealDB connected for Knowledge Graph synchronization")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        if not self._db or not self._db.is_connected:
            return None

        if hook == WikiHook.ON_NODE_INGEST:
            # 当编译器提取并索引完一个节点后触发同步
            node: KnowledgeNode = payload.get("node")
            relations: list[KnowledgeRelation] = payload.get("relations", [])
            
            if node:
                await self._sync_node(node)
            for rel in relations:
                await self._sync_relation(rel)
                
        elif hook == WikiHook.POST_COMPILE:
            # 编译完成后可选的清理或元数据同步
            logger.info("🏁 Wiki compilation finished, SurrealDB sync confirmed.")
            
        return None

    async def _sync_node(self, node: KnowledgeNode) -> None:
        """同步单个知识节点。"""
        try:
            # 将 KnowledgeNode 转换为字典 (包含元数据和 frontmatter)
            node_data = node.to_frontmatter_dict()
            # 注入正文和向量哈希
            node_data["body"] = node.body
            node_data["embedding_hash"] = node.embedding_hash
            
            await self._db.upsert_knowledge_node(node_data)
            logger.debug(f"Synced node to SurrealDB: {node.id}")
        except Exception as e:
            logger.error(f"Failed to sync node {node.id} to SurrealDB: {e}")

    async def _sync_relation(self, rel: KnowledgeRelation) -> None:
        """同步单个关系。"""
        try:
            await self._db.save_relation(
                from_entity=rel.from_id,
                to_entity=rel.to_id,
                relation_type=rel.relation_type.value,
                properties={
                    "weight": rel.weight,
                    "evidence": rel.evidence,
                    "confidence": rel.confidence
                }
            )
        except Exception as e:
            logger.error(f"Failed to sync relation {rel} to SurrealDB: {e}")
