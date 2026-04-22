"""
Coda Knowledge Engine V6.0 — Atlas Index Layer
SQLite-vec + FTS5 统一索引层。

实现:
  - 向量索引 (sqlite-vec): 语义检索
  - 全文索引 (FTS5): 关键词检索 + 3x 标题加权
  - 4D 融合检索: semantic + keyword + temporal + relational
  - BM25 强信号探针: 跳过无效 LLM 调用
  - 位置感知 RRF 融合: 分段混合权重
  - 上下文感知片段提取
"""

from __future__ import annotations

from ..base_plugin import WikiPlugin, WikiHook, WikiPluginContext

import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import struct
import time
from pathlib import Path
from typing import Any

from ..akp_types import (
    KnowledgeNode, KnowledgeRelation, NodeType, NodeStatus,
    RelationType, StorageLayer,
)

logger = logging.getLogger("Coda.wiki.atlas")

# ── RRF 常量 ──
RRF_K = 60  # 标准 RRF 常量
TOP_RANK_BONUS = 0.05  # 排名第 1 的额外奖励


def _serialize_f32(vector: list[float]) -> bytes:
    """将浮点向量序列化为 little-endian float32 字节串 (sqlite-vec 格式)。"""
    return struct.pack(f"<{len(vector)}f", *vector)


def _deserialize_f32(blob: bytes) -> list[float]:
    """从字节串反序列化为浮点向量。"""
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


class AtlasIndex(WikiPlugin):
    """
    SQLite-vec + FTS5 统一索引层 ("文件即真理" 的编译产物)。

    数据表:
      - nodes: 知识节点元数据
      - node_embeddings: 向量索引 (sqlite-vec virtual table)
      - node_fts: FTS5 全文索引 (标题 3x 加权)
      - relations: 知识关系边
      - audit_log: 审计日志
    """
    name = "atlas"

    def __init__(self, db_path: str | Path | None = None, embedding_dim: int = 2048):
        self._db_path = str(db_path) if db_path else None
        self._dim = embedding_dim
        self._conn: sqlite3.Connection | None = None
        self._vec_enabled = False

    async def initialize(self, ctx: WikiPluginContext) -> None:
        """插件初始化入口。"""
        if not self._db_path:
            self._db_path = str(Path(ctx.wiki_dir) / "_meta" / "atlas.db")
        self.connect()
        logger.info(f"🗂️ Atlas plugin initialized: vec_enabled={self._vec_enabled}")

    async def on_hook(self, hook: WikiHook, payload: Any = None) -> Any:
        """响应 Wiki 钩子。"""
        if hook == WikiHook.ON_SHUTDOWN:
            self.close()
            logger.info("🗂️ Atlas plugin closed")
        return None

    def connect(self) -> None:
        """打开数据库连接并初始化 Schema。"""
        db_dir = Path(self._db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=OFF")  # 允许 wanted pages (引用尚不存在的节点)

        # 尝试加载 sqlite-vec
        try:
            import sqlite_vec
            self._conn.enable_load_extension(True)
            sqlite_vec.load(self._conn)
            self._vec_enabled = True
            logger.info("✅ sqlite-vec loaded successfully")
        except (ImportError, Exception) as e:
            logger.warning(f"sqlite-vec not available ({e}), vector search disabled. Using TF-IDF fallback.")
            self._vec_enabled = False

        self._create_schema()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def _create_schema(self) -> None:
        """创建所有必要的表和索引。"""
        assert self._conn is not None

        # ── 节点元数据表 ──
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                node_type TEXT NOT NULL DEFAULT 'concept',
                status TEXT NOT NULL DEFAULT 'draft',
                confidence REAL DEFAULT 0.5,
                epistemic_tag TEXT DEFAULT 'speculative',
                authority TEXT DEFAULT 'inferred',
                load_bearing INTEGER DEFAULT 0,
                pii_shield TEXT DEFAULT 'raw',
                insight_density INTEGER DEFAULT 5,
                word_count INTEGER DEFAULT 0,
                backlink_count INTEGER DEFAULT 0,
                access_count INTEGER DEFAULT 0,
                activation_score REAL DEFAULT 1.0,
                content_hash TEXT DEFAULT '',
                file_path TEXT DEFAULT '',
                quality_gate TEXT DEFAULT 'pending_review',
                source_origin_hash TEXT DEFAULT '',
                verified_by TEXT DEFAULT '',
                truncated INTEGER DEFAULT 0,
                body_preview TEXT DEFAULT '',
                created_at REAL DEFAULT 0,
                updated_at REAL DEFAULT 0,
                last_audit TEXT DEFAULT '',
                meta_json TEXT DEFAULT '{}'
            )
        """)

        # ── FTS5 全文索引 (标题 3x 加权, standalone — 不绑定 nodes 表) ──
        self._conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS node_fts USING fts5(
                title,
                body,
                node_id UNINDEXED,
                tokenize='unicode61'
            )
        """)

        # ── 向量索引 (sqlite-vec) ──
        if self._vec_enabled:
            try:
                self._conn.execute(f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS node_embeddings
                    USING vec0(
                        node_id TEXT PRIMARY KEY,
                        embedding float[{self._dim}]
                    )
                """)
            except Exception as e:
                logger.warning(f"Failed to create vec0 table: {e}")
                self._vec_enabled = False

        # ── 关系表 (无外键约束: 允许引用尚未索引的 wanted pages) ──
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS relations (
                id TEXT PRIMARY KEY,
                from_id TEXT NOT NULL,
                to_id TEXT NOT NULL,
                relation_type TEXT NOT NULL DEFAULT 'related_to',
                weight REAL DEFAULT 1.0,
                load_bearing INTEGER DEFAULT 0,
                confidence REAL DEFAULT 1.0,
                source TEXT DEFAULT '',
                created_at REAL DEFAULT 0
            )
        """)

        # ── 审计日志表 ──
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                target TEXT DEFAULT '',
                detail TEXT DEFAULT '',
                agent_id TEXT DEFAULT '',
                task_id TEXT DEFAULT '',
                conversation_id TEXT DEFAULT '',
                timestamp REAL DEFAULT 0
            )
        """)

        # ── 索引 ──
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_status ON nodes(status)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(node_type)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_hash ON nodes(content_hash)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_relations_from ON relations(from_id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_relations_to ON relations(to_id)")

        self._conn.commit()

    # ════════════════════════════════════════════
    #  CRUD 操作
    # ════════════════════════════════════════════

    def upsert_node(self, node: KnowledgeNode, embedding: list[float] | None = None) -> None:
        """插入或更新知识节点 (含 FTS 和向量索引)。"""
        assert self._conn is not None

        meta = {
            "depends_on": node.depends_on,
            "extends": node.extends,
            "contradicts": node.contradicts,
            "references": node.references,
            "falsifiable": node.falsifiable,
            "falsification": node.falsification,
            "derived_from_sources": node.derived_from_sources,
            "frozen_reason": node.frozen_reason,
        }

        self._conn.execute("""
            INSERT INTO nodes (
                id, title, node_type, status, confidence, epistemic_tag,
                authority, load_bearing, pii_shield, insight_density,
                word_count, backlink_count, access_count, activation_score,
                content_hash, file_path, quality_gate, source_origin_hash,
                verified_by, truncated, body_preview, created_at, updated_at,
                last_audit, meta_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title, node_type=excluded.node_type,
                status=excluded.status, confidence=excluded.confidence,
                epistemic_tag=excluded.epistemic_tag, authority=excluded.authority,
                load_bearing=excluded.load_bearing, pii_shield=excluded.pii_shield,
                insight_density=excluded.insight_density, word_count=excluded.word_count,
                content_hash=excluded.content_hash, file_path=excluded.file_path,
                quality_gate=excluded.quality_gate, source_origin_hash=excluded.source_origin_hash,
                verified_by=excluded.verified_by, truncated=excluded.truncated,
                body_preview=excluded.body_preview, updated_at=excluded.updated_at,
                last_audit=excluded.last_audit, meta_json=excluded.meta_json
        """, (
            node.id, node.title, node.node_type.value, node.status.value,
            node.confidence, node.epistemic_tag.value, node.authority.value,
            int(node.load_bearing), node.pii_shield.value, node.insight_density,
            node.word_count, node.backlink_count, node.access_count,
            node.activation_score, node.content_hash, node.file_path,
            node.quality_gate.value, node.source_origin_hash,
            node.verified_by, int(node.truncated), node.body[:500],
            node.created_at, node.updated_at, node.last_audit,
            json.dumps(meta, ensure_ascii=False),
        ))

        # ── 更新 FTS 索引 ──
        self._conn.execute("DELETE FROM node_fts WHERE node_id = ?", (node.id,))
        self._conn.execute(
            "INSERT INTO node_fts (node_id, title, body) VALUES (?, ?, ?)",
            (node.id, node.title, node.body[:10000]),
        )

        # ── 更新向量索引 ──
        if embedding and self._vec_enabled:
            vec_bytes = _serialize_f32(embedding)
            try:
                self._conn.execute(
                    "DELETE FROM node_embeddings WHERE node_id = ?", (node.id,)
                )
                self._conn.execute(
                    "INSERT INTO node_embeddings (node_id, embedding) VALUES (?, ?)",
                    (node.id, vec_bytes),
                )
                node.embedding_hash = hashlib.md5(vec_bytes).hexdigest()[:12]
            except Exception as e:
                logger.warning(f"Vector index update failed for {node.id}: {e}")

        self._conn.commit()

    def delete_node(self, node_id: str) -> None:
        """删除节点及其关联索引。"""
        assert self._conn is not None
        self._conn.execute("DELETE FROM node_fts WHERE node_id = ?", (node_id,))
        if self._vec_enabled:
            try:
                self._conn.execute("DELETE FROM node_embeddings WHERE node_id = ?", (node_id,))
            except Exception:
                pass
        self._conn.execute("DELETE FROM relations WHERE from_id = ? OR to_id = ?", (node_id, node_id))
        self._conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
        self._conn.commit()

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        """通过 ID 获取节点。"""
        assert self._conn is not None
        row = self._conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        return dict(row) if row else None

    def upsert_relation(self, relation: KnowledgeRelation) -> None:
        """插入或更新关系边。"""
        assert self._conn is not None
        rel_id = hashlib.md5(
            f"{relation.from_id}:{relation.relation_type.value}:{relation.to_id}".encode()
        ).hexdigest()[:16]

        self._conn.execute("""
            INSERT INTO relations (id, from_id, to_id, relation_type, weight, load_bearing, confidence, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                weight=excluded.weight, confidence=excluded.confidence, source=excluded.source
        """, (
            rel_id, relation.from_id, relation.to_id,
            relation.relation_type.value, relation.weight,
            int(relation.load_bearing), relation.confidence,
            relation.source, relation.created_at,
        ))
        self._conn.commit()

    def log_audit(self, action: str, target: str = "", detail: str = "",
                  agent_id: str = "", task_id: str = "", conversation_id: str = "") -> None:
        """写入审计日志。"""
        assert self._conn is not None
        self._conn.execute("""
            INSERT INTO audit_log (action, target, detail, agent_id, task_id, conversation_id, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (action, target, detail, agent_id, task_id, conversation_id, time.time()))
        self._conn.commit()

    # ════════════════════════════════════════════
    #  4D 融合检索 (4D-Fusion Recall)
    # ════════════════════════════════════════════

    def search(
        self,
        query: str,
        query_embedding: list[float] | None = None,
        top_k: int = 10,
        weights: dict[str, float] | None = None,
        favor_recency: bool = False,
        status_filter: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        4D 融合检索:
          - Semantic (向量相似度)
          - Keyword (FTS5 BM25)
          - Temporal (时间衰减)
          - Relational (关系密度 / PageRank 简化版)

        含 BM25 强信号探针: 如果 FTS 首位分数极高, 跳过向量搜索。
        """
        w = weights or {"sem": 0.4, "fts": 0.3, "temp": 0.15, "rel": 0.15}

        # ── Step 1: FTS5 关键词检索 ──
        fts_results = self._search_fts(query, top_k * 3) if query.strip() else []

        # ── BM25 强信号探针 ──
        skip_vector = False
        if len(fts_results) >= 2:
            score_gap = fts_results[0]["score"] - fts_results[1]["score"]
            if score_gap > 0.15 and fts_results[0]["score"] > 0.7:
                skip_vector = True
                logger.debug(f"BM25 strong signal probe triggered (gap={score_gap:.3f}), skipping vector search")

        # ── Step 2: 向量语义检索 ──
        vec_results: list[dict[str, Any]] = []
        if query_embedding and self._vec_enabled and not skip_vector:
            vec_results = self._search_vector(query_embedding, top_k * 3)

        # ── Step 3: 融合排名 ──
        all_ids = set()
        fts_rank = {r["node_id"]: i for i, r in enumerate(fts_results)}
        vec_rank = {r["node_id"]: i for i, r in enumerate(vec_results)}
        all_ids.update(fts_rank.keys())
        all_ids.update(vec_rank.keys())

        scored: list[tuple[float, str]] = []
        now = time.time()

        for node_id in all_ids:
            # 语义分 (RRF)
            sem_score = 0.0
            if node_id in vec_rank:
                rank = vec_rank[node_id]
                sem_score = 1.0 / (RRF_K + rank + 1)
                if rank == 0:
                    sem_score += TOP_RANK_BONUS

            # 关键词分 (RRF)
            fts_score = 0.0
            if node_id in fts_rank:
                rank = fts_rank[node_id]
                fts_score = 1.0 / (RRF_K + rank + 1)
                if rank == 0:
                    fts_score += TOP_RANK_BONUS

            # 时间衰减分
            temp_score = 0.0
            node_data = self.get_node(node_id)
            if node_data:
                updated_at = node_data.get("updated_at", 0)
                if isinstance(updated_at, (int, float)) and updated_at > 0:
                    days_old = (now - updated_at) / 86400
                    temp_score = math.exp(-0.02 * days_old)  # 半衰期 ~35 天
                    if favor_recency:
                        temp_score = math.exp(-0.05 * days_old)  # 加速衰减

            # 关系密度分
            rel_score = 0.0
            if node_data:
                in_count = self._count_relations(node_id, direction="in")
                out_count = self._count_relations(node_id, direction="out")
                rel_score = math.log1p(in_count + out_count) / 10.0  # 归一化

            # 加权融合
            final = (
                w.get("sem", 0.4) * sem_score
                + w.get("fts", 0.3) * fts_score
                + w.get("temp", 0.15) * temp_score
                + w.get("rel", 0.15) * rel_score
            )

            # 状态过滤
            if status_filter and node_data:
                if node_data.get("status") not in status_filter:
                    continue

            scored.append((final, node_id))

        scored.sort(key=lambda x: x[0], reverse=True)

        # ── Step 4: 组装结果 ──
        results: list[dict[str, Any]] = []
        for score, node_id in scored[:top_k]:
            node_data = self.get_node(node_id)
            if node_data:
                node_data["search_score"] = round(score, 6)
                # 上下文感知片段提取
                if query.strip():
                    node_data["snippet"] = self._extract_best_snippet(
                        node_data.get("body_preview", ""), query
                    )
                results.append(node_data)

        return results

    def _search_fts(self, query: str, limit: int = 30) -> list[dict[str, Any]]:
        """FTS5 全文检索 (标题 3x 加权通过 bm25 内置)。"""
        assert self._conn is not None
        try:
            rows = self._conn.execute("""
                SELECT node_id, bm25(node_fts, 3.0, 1.0) AS score
                FROM node_fts
                WHERE node_fts MATCH ?
                ORDER BY score ASC
                LIMIT ?
            """, (query, limit)).fetchall()
            return [{"node_id": row["node_id"], "score": abs(row["score"])} for row in rows]
        except Exception as e:
            logger.debug(f"FTS search failed: {e}")
            return []

    def _search_vector(self, embedding: list[float], limit: int = 30) -> list[dict[str, Any]]:
        """sqlite-vec 向量检索。"""
        assert self._conn is not None and self._vec_enabled
        try:
            vec_bytes = _serialize_f32(embedding)
            rows = self._conn.execute("""
                SELECT node_id, distance
                FROM node_embeddings
                WHERE embedding MATCH ?
                AND k = ?
            """, (vec_bytes, limit)).fetchall()
            return [{"node_id": row["node_id"], "score": 1.0 / (1.0 + row["distance"])} for row in rows]
        except Exception as e:
            logger.debug(f"Vector search failed: {e}")
            return []

    def _count_relations(self, node_id: str, direction: str = "both") -> int:
        """计算关系数量。"""
        assert self._conn is not None
        if direction == "in":
            row = self._conn.execute("SELECT COUNT(*) c FROM relations WHERE to_id = ?", (node_id,)).fetchone()
        elif direction == "out":
            row = self._conn.execute("SELECT COUNT(*) c FROM relations WHERE from_id = ?", (node_id,)).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) c FROM relations WHERE from_id = ? OR to_id = ?", (node_id, node_id)
            ).fetchone()
        return row["c"] if row else 0

    def _extract_best_snippet(self, text: str, query: str, max_len: int = 200) -> str:
        """
        上下文感知片段提取 (LLM-Knowledge-Base)。
        扫描全文找到包含搜索词密度最高的区域。
        """
        if not text or not query:
            return text[:max_len]

        query_terms = [t.lower() for t in query.split() if len(t) > 1]
        sentences = re.split(r'[。.!?！？\n]', text)

        best_score = 0
        best_sentence = text[:max_len]

        for sent in sentences:
            sent = sent.strip()
            if len(sent) < 10:
                continue
            score = sum(1 for term in query_terms if term in sent.lower())
            if score > best_score:
                best_score = score
                best_sentence = sent

        return best_sentence[:max_len]

    # ════════════════════════════════════════════
    #  图谱查询
    # ════════════════════════════════════════════

    def get_neighbors(self, node_id: str, max_hops: int = 1) -> list[dict[str, Any]]:
        """获取节点的邻居 (支持多跳)。"""
        assert self._conn is not None
        visited: set[str] = {node_id}
        frontier: set[str] = {node_id}
        all_neighbors: list[dict[str, Any]] = []

        for hop in range(max_hops):
            next_frontier: set[str] = set()
            for nid in frontier:
                rows = self._conn.execute("""
                    SELECT r.*, n.title, n.node_type, n.status
                    FROM relations r
                    JOIN nodes n ON (
                        CASE WHEN r.from_id = ? THEN r.to_id ELSE r.from_id END = n.id
                    )
                    WHERE r.from_id = ? OR r.to_id = ?
                """, (nid, nid, nid)).fetchall()
                for row in rows:
                    neighbor_id = row["to_id"] if row["from_id"] == nid else row["from_id"]
                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        next_frontier.add(neighbor_id)
                        all_neighbors.append({
                            "node_id": neighbor_id,
                            "title": row["title"],
                            "node_type": row["node_type"],
                            "relation": row["relation_type"],
                            "direction": "outgoing" if row["from_id"] == nid else "incoming",
                            "hop": hop + 1,
                            "load_bearing": bool(row["load_bearing"]),
                        })
            frontier = next_frontier

        return all_neighbors

    def find_load_bearing_chain(self, node_id: str) -> list[str]:
        """追踪承重边依赖链 (用于级联失效分析)。"""
        assert self._conn is not None
        chain: list[str] = []
        visited: set[str] = set()
        queue = [node_id]

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            chain.append(current)

            rows = self._conn.execute("""
                SELECT to_id FROM relations
                WHERE from_id = ? AND load_bearing = 1
            """, (current,)).fetchall()
            for row in rows:
                if row["to_id"] not in visited:
                    queue.append(row["to_id"])

        return chain

    def find_orphans(self) -> list[dict[str, Any]]:
        """查找孤儿页面 (入度 = 0)。"""
        assert self._conn is not None
        rows = self._conn.execute("""
            SELECT n.id, n.title, n.node_type, n.status, n.word_count
            FROM nodes n
            LEFT JOIN relations r ON r.to_id = n.id
            WHERE r.id IS NULL AND n.status != 'archived'
            ORDER BY n.updated_at DESC
        """).fetchall()
        return [dict(r) for r in rows]

    def find_wanted_pages(self) -> list[dict[str, Any]]:
        """
        统计"需求页面" — 被引用但不存在的知识节点 (Rock-Star)。
        按引用频次排序, 驱动知识扩充优先级。
        """
        assert self._conn is not None
        rows = self._conn.execute("""
            SELECT r.to_id AS wanted_id, COUNT(*) AS ref_count
            FROM relations r
            LEFT JOIN nodes n ON r.to_id = n.id
            WHERE n.id IS NULL
            GROUP BY r.to_id
            ORDER BY ref_count DESC
            LIMIT 50
        """).fetchall()
        return [{"wanted_id": r["wanted_id"], "ref_count": r["ref_count"]} for r in rows]

    # ════════════════════════════════════════════
    #  漂移检测 (Drift Detection)
    # ════════════════════════════════════════════

    def detect_drift(self, wiki_dir: str | Path) -> dict[str, list[str]]:
        """
        Wiki-Index 一致性审计:
        对比 Wiki 文件目录与索引中的记录。
        
        返回:
          - orphaned_in_index: 索引中有但文件不存在
          - missing_in_index: 文件存在但索引中没有
        """
        assert self._conn is not None
        wiki_path = Path(wiki_dir)

        # 索引中的所有文件路径
        rows = self._conn.execute("SELECT id, file_path FROM nodes").fetchall()
        indexed_paths = {row["file_path"]: row["id"] for row in rows if row["file_path"]}

        # 文件系统中的所有 .md 文件
        physical_files = set()
        for md_file in wiki_path.rglob("*.md"):
            physical_files.add(str(md_file))

        orphaned = [path for path in indexed_paths if path and path not in physical_files]
        missing = [path for path in physical_files if path not in indexed_paths]

        return {
            "orphaned_in_index": orphaned,
            "missing_in_index": missing,
        }

    # ════════════════════════════════════════════
    #  统计
    # ════════════════════════════════════════════

    def get_stats(self) -> dict[str, Any]:
        """获取索引统计信息。"""
        assert self._conn is not None
        node_count = self._conn.execute("SELECT COUNT(*) c FROM nodes").fetchone()["c"]
        relation_count = self._conn.execute("SELECT COUNT(*) c FROM relations").fetchone()["c"]
        
        type_dist = {}
        for row in self._conn.execute("SELECT node_type, COUNT(*) c FROM nodes GROUP BY node_type").fetchall():
            type_dist[row["node_type"]] = row["c"]

        status_dist = {}
        for row in self._conn.execute("SELECT status, COUNT(*) c FROM nodes GROUP BY status").fetchall():
            status_dist[row["status"]] = row["c"]

        return {
            "node_count": node_count,
            "relation_count": relation_count,
            "type_distribution": type_dist,
            "status_distribution": status_dist,
            "vec_enabled": self._vec_enabled,
            "embedding_dim": self._dim,
        }

