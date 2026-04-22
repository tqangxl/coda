"""
Coda Knowledge Engine V7.0 — SurrealDB Atlas Bridge.
联邦知识图谱同步插件。

将 Wiki 知识图谱按 project_id/layer 分区同步到 SurrealDB 全局存储，
支持跨项目的图遍历查询与联邦搜索。
"""

from __future__ import annotations
import logging
import time
from typing import Any, TYPE_CHECKING
from ..base_plugin import WikiPlugin, WikiHook, WikiPluginContext
from engine.db import SurrealStore

if TYPE_CHECKING:
    from ..akp_types import KnowledgeNode, KnowledgeRelation

logger = logging.getLogger("Coda.wiki.surreal_atlas")


class SurrealAtlasIndex(WikiPlugin):
    """
    SurrealDB 联邦知识同步插件 (V7.0)。

    功能:
      - 将本地编译的知识节点按 project_id 分区同步到 SurrealDB。
      - 支持跨项目的图关系建立 (跨越不同 project_id 的 RELATE 边)。
      - 在初始化时注册当前项目的挂载订阅关系。
    """
    name = "surreal_atlas"

    def __init__(self) -> None:
        self._db: SurrealStore | None = None
        self._ctx: WikiPluginContext | None = None
        self._project_id: str = "default"
        self._layer: int = 3

    async def initialize(self, ctx: WikiPluginContext) -> None:
        self._ctx = ctx

        # 从引擎配置获取联邦参数
        cfg = ctx.config
        if cfg is not None:
            self._project_id = getattr(cfg, "project_id", "default")
            self._layer = getattr(cfg, "layer", 3)
            mounts: list[str] = getattr(cfg, "mounts", [])
        else:
            mounts = []

        # 建立 SurrealDB 连接
        from engine.db import SurrealStore
        self._db = SurrealStore()
        connected = await self._db.connect()

        if not connected:
            logger.warning(
                "⚠️ SurrealDB not connected — SurrealAtlas disabled (local SQLite only)"
            )
            return

        logger.info(
            f"✅ SurrealDB connected | project={self._project_id} layer=L{self._layer}"
        )

        # 注册挂载订阅关系 (将当前项目订阅到上游知识库)
        for upstream in mounts:
            registered = await self._db.add_mount(
                subscriber=self._project_id,
                upstream=upstream,
                access="readonly",
            )
            if registered:
                logger.info(f"📌 Mounted upstream: {self._project_id} → {upstream}")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        if not self._db or not self._db.is_connected:
            return None

        if hook == WikiHook.ON_NODE_INGEST:
            node: KnowledgeNode = payload.get("node")
            relations: list[KnowledgeRelation] = payload.get("relations", [])

            if node:
                await self._sync_node(node)
            for rel in relations:
                await self._sync_relation(rel)

        elif hook == WikiHook.ON_NODE_DELETE:
            node_id = payload.get("node_id")
            project_id = payload.get("project_id", self._project_id)
            if node_id:
                await self._delete_node(node_id, project_id)

        elif hook == WikiHook.POST_COMPILE:
            logger.info(
                f"🏁 SurrealDB sync confirmed for project '{self._project_id}'"
            )
            # ── [V7.1] 触发前端实时更新 ──
            try:
                import httpx
                import asyncio
                # 尝试异步发送通知到主进程 API
                async def notify():
                    async with httpx.AsyncClient() as client:
                        await client.post("http://127.0.0.1:11002/engine/notify-update", json={"type": "sync_complete"})
                
                asyncio.create_task(notify())
            except Exception as e:
                logger.debug(f"Live notification failed (expected if server not on 11002): {e}")

        return None

    async def _sync_node(self, node: KnowledgeNode) -> None:
        """同步单个知识节点，注入联邦分区键。"""
        if not self._db:
            return
        try:
            node_data = node.to_frontmatter_dict()
            node_data["body"] = node.body
            node_data["embedding_hash"] = node.embedding_hash

            # V7.0: 注入联邦元数据
            node_data["project_id"] = self._project_id
            node_data["layer"] = self._layer
            # L0/L1 层节点默认只读
            node_data["readonly"] = node_data.get("readonly", self._layer <= 1)
            node_data["source_format"] = getattr(node, "source_format", "md")
            
            # [超级进阶] 注入拼音元数据
            try:
                from pypinyin import pinyin, Style
                title = node.title
                # 生成全拼 (如: zhishitupu)
                full_pinyin = "".join([i[0] for i in pinyin(title, style=Style.NORMAL)])
                # 生成首字母缩写 (如: zztp)
                abbr_pinyin = "".join([i[0][0] for i in pinyin(title, style=Style.FIRST_LETTER)])
                
                node_data["pinyin_title"] = full_pinyin.lower()
                node_data["pinyin_abbr"] = abbr_pinyin.lower()
            except ImportError:
                pass

            # ── [V7.1] Memory Horizon 写入 SurrealDB ──
            node_data["memory_horizon"] = node.memory_horizon.value
            node_data["compile_depth"] = node.memory_horizon.compile_depth
            node_data["max_body_chars"] = node.memory_horizon.max_body_chars
            
            # 计算过期时间戳 (expires_at)
            ttl = node.ttl_hours if node.ttl_hours is not None else node.memory_horizon.ttl_hours_default
            if ttl is not None:
                node_data["expires_at"] = time.time() + (ttl * 3600)
            else:
                node_data["expires_at"] = None

            await self._db.upsert_knowledge_node(node_data)
            logger.debug(f"Synced node [{self._project_id}] {node.id}")
        except Exception as e:
            logger.error(f"Failed to sync node {node.id}: {e}")

    async def _delete_node(self, node_id: str, project_id: str) -> None:
        """从 SurrealDB 中物理移除知识节点及其所有关联。"""
        if not self._db or not self._db.is_connected:
            return
        try:
            # 执行删除 (V7.0 联邦分区删除)
            await self._db.delete_knowledge_node(project_id, node_id)
        except Exception as e:
            logger.error(f"Failed to delete node {node_id}: {e}")

    async def _sync_relation(self, rel: KnowledgeRelation) -> None:
        """同步关系边，支持跨项目节点间的关联。"""
        if not self._db:
            return
        try:
            # V7.0: 必须使用联邦完整的 Record ID
            from_full = f"wiki_nodes:['{self._project_id}', '{rel.from_id}']"
            to_full = f"wiki_nodes:['{self._project_id}', '{rel.to_id}']"
            
            # 如果 to_id 看起来像是一个已经包含 project 的复合 ID (例如 [[other_project:node_id]])
            if ":" in rel.to_id and "[" not in rel.to_id:
                parts = rel.to_id.split(":", 1)
                to_full = f"wiki_nodes:['{parts[0]}', '{parts[1]}']"

            await self._db.save_relation(
                from_entity=from_full,
                to_entity=to_full,
                relation_type=rel.relation_type.value,
                properties={
                    "weight": rel.weight,
                    "confidence": rel.confidence,
                    "source": rel.source,
                    "from_project": self._project_id,
                    "local_id": getattr(rel, "id", None)
                }
            )
            logger.debug(f"Synced relation [{self._project_id}] {rel.from_id} -> {rel.to_id}")
        except Exception as e:
            logger.error(f"Failed to sync relation {rel}: {e}")

    async def get_stats(self) -> dict[str, Any]:
        """获取 SurrealDB 端的联邦统计信息。"""
        if not self._db or not self._db.is_connected:
            return {"error": "Not connected"}
        
        try:
            # 统计当前项目的节点和关系
            res = await self._db._safe_query(
                "SELECT count() as count, node_type FROM wiki_nodes WHERE project_id = $pid GROUP BY node_type",
                {"pid": self._project_id}
            )
            node_stats = self._db._extract_result(res)
            
            res_rel = await self._db._safe_query(
                "SELECT count() as count FROM (SELECT * FROM ->? WHERE from_project = $pid)",
                {"pid": self._project_id}
            )
            rel_count = self._db._extract_result(res_rel)[0].get("count", 0) if self._db._extract_result(res_rel) else 0
            
            return {
                "project_id": self._project_id,
                "node_counts": {r["node_type"]: r["count"] for r in node_stats},
                "relation_count": rel_count,
                "total_nodes": sum(r["count"] for r in node_stats)
            }
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {"error": str(e)}

    async def register_cross_project_link(
        self,
        from_node_id: str,
        to_project_id: str,
        to_node_id: str,
        relation_type: str = "references",
        confidence: float = 0.9,
    ) -> bool:
        """
        显式建立跨项目的知识关联边。
        
        允许当前项目的节点引用另一个项目的节点，
        例如: 个人合同文件 → 引用 → L0 法律条款。
        """
        if not self._db or not self._db.is_connected:
            return False
        try:
            # 构造完整的联邦 Record ID
            from_full = f"wiki_nodes:['{self._project_id}', '{from_node_id}']"
            to_full = f"wiki_nodes:['{to_project_id}', '{to_node_id}']"

            await self._db.save_relation(
                from_entity=from_full,
                to_entity=to_full,
                relation_type=relation_type,
                properties={
                    "confidence": confidence,
                    "cross_project": True,
                    "from_project": self._project_id,
                    "to_project": to_project_id,
                    "source": "explicit_link",
                }
            )
            logger.info(
                f"🔗 Cross-project link: [{self._project_id}]{from_node_id} "
                f"→ [{to_project_id}]{to_node_id}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to register cross-project link: {e}")
            return False

    async def migrate_local_to_surreal(self) -> dict[str, Any]:
        """
        [One-way Migration] 将本地 SQLite (AtlasIndex) 的存量数据迁移到 SurrealDB。
        """
        if not self._db or not self._db.is_connected:
            return {"error": "SurrealDB not connected"}
        
        local_atlas = self._ctx.registry.get_plugin("atlas") if self._ctx else None
        if not local_atlas:
            return {"error": "Local Atlas plugin not found"}
        
        stats = {"nodes": 0, "relations": 0, "errors": 0}
        
        try:
            # 1. 迁移节点
            # 获取本地所有节点 ID
            assert local_atlas._conn is not None
            rows = local_atlas._conn.execute("SELECT id FROM nodes").fetchall()
            node_ids = [row["id"] for row in rows]
            
            from ..akp_types import KnowledgeNode, KnowledgeRelation, RelationType
            
            for nid in node_ids:
                try:
                    raw_node = local_atlas.get_node(nid)
                    if raw_node:
                        # 转换回 KnowledgeNode 对象 (简化处理)
                        node = KnowledgeNode(
                            id=raw_node["id"],
                            title=raw_node["title"],
                            body=raw_node.get("body", ""),
                            node_type=raw_node["node_type"],
                            status=raw_node["status"]
                        )
                        # 补充元数据
                        for k, v in raw_node.items():
                            if hasattr(node, k) and k not in ("id", "title", "body"):
                                setattr(node, k, v)
                        
                        await self._sync_node(node)
                        stats["nodes"] += 1
                except Exception as e:
                    logger.error(f"Migration error for node {nid}: {e}")
                    stats["errors"] += 1

            # 2. 迁移关系
            rel_rows = local_atlas._conn.execute("SELECT * FROM relations").fetchall()
            for rrow in rel_rows:
                try:
                    rel = KnowledgeRelation(
                        from_id=rrow["from_id"],
                        to_id=rrow["to_id"],
                        relation_type=RelationType(rrow["relation_type"]),
                        weight=rrow["weight"],
                        confidence=rrow["confidence"],
                        source=rrow["source"]
                    )
                    await self._sync_relation(rel)
                    stats["relations"] += 1
                except Exception as e:
                    logger.error(f"Migration error for relation: {e}")
                    stats["errors"] += 1
                    
            logger.info(f"🚀 Migration complete: {stats}")
            return stats
        except Exception as e:
            logger.error(f"Critical migration failure: {e}")
            return {"error": str(e), "stats": stats}
