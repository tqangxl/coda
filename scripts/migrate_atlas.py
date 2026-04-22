import asyncio
import os
import sys
import sqlite3
import hashlib
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.db import SurrealStore
from engine.plugins.wiki.akp_types import KnowledgeNode, KnowledgeRelation, RelationType

async def migrate_sqlite_to_surreal(db_path: Path, store: SurrealStore, project_id: str):
    """迁移单个 SQLite 数据库到 SurrealDB。"""
    if not db_path.exists():
        print(f"⏩ Skipping {db_path} (Not found)")
        return
    
    print(f"📦 Migrating {db_path} -> SurrealDB [Project: {project_id}]")
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    stats = {"nodes": 0, "relations": 0, "errors": 0}
    
    try:
        # 1. 迁移节点
        rows = conn.execute("SELECT * FROM nodes").fetchall()
        for row in rows:
            try:
                node_dict = dict(row)
                # 尝试获取完整 body
                try:
                    fts_row = conn.execute("SELECT body FROM node_fts WHERE node_id = ?", (row["id"],)).fetchone()
                    if fts_row:
                        node_dict["body"] = fts_row["body"]
                except:
                    pass
                
                # 构造 KnowledgeNode
                node = KnowledgeNode.from_dict(node_dict)
                node.project_id = project_id
                
                # 同步到 SurrealDB
                # 我们使用 SurrealStore 的 upsert_knowledge_node (传入 dict)
                await store.upsert_knowledge_node(node.to_dict())
                stats["nodes"] += 1
            except Exception as e:
                print(f"❌ Error migrating node {row['id']}: {e}")
                stats["errors"] += 1

        # 2. 迁移关系
        rel_rows = conn.execute("SELECT * FROM relations").fetchall()
        for rrow in rel_rows:
            try:
                # 构造 Record ID
                # 关键: 处理 node_id 中的单引号和反斜杠
                clean_from = rrow['from_id'].replace("\\", "\\\\").replace("'", "\\'")
                clean_to = rrow['to_id'].replace("\\", "\\\\").replace("'", "\\'")
                from_full = f"wiki_nodes:['{project_id}', '{clean_from}']"
                to_full = f"wiki_nodes:['{project_id}', '{clean_to}']"
                
                await store.save_relation(
                    from_entity=from_full,
                    to_entity=to_full,
                    relation_type=rrow["relation_type"],
                    properties={
                        "weight": rrow["weight"],
                        "confidence": rrow["confidence"],
                        "source": rrow["source"],
                        "project_id": project_id
                    }
                )
                stats["relations"] += 1
            except Exception as e:
                print(f"❌ Error migrating relation: {e}")
                stats["errors"] += 1
                
        print(f"✅ Migrated {project_id}: {stats}")
        return stats
    finally:
        conn.close()

async def main():
    print("🚀 Starting Coda Federated Migration (SQLite -> SurrealDB)")
    
    # 1. 初始化 SurrealDB
    db_url = os.getenv("SURREALDB_URL", "ws://127.0.0.1:11001/rpc")
    store = SurrealStore()
    await store.connect(url=db_url)
    
    # 确保 Schema 存在
    await store.ensure_wiki_schema()
    
    # 2. 扫描可能的数据库文件
    targets = [
        (PROJECT_ROOT / ".coda" / "wiki" / "_meta" / "atlas.db", "wiki"),
        (PROJECT_ROOT / "agents" / "_meta" / "atlas.db", "agents"),
        (PROJECT_ROOT / "scratch" / "wiki_test" / "_meta" / "atlas.db", "test"),
    ]
    
    total_stats = {"nodes": 0, "relations": 0, "errors": 0}
    
    for db_path, project_id in targets:
        stats = await migrate_sqlite_to_surreal(db_path, store, project_id)
        if stats:
            for k in total_stats:
                total_stats[k] += stats.get(k, 0)
    
    print("\n" + "═"*40)
    print(f"🏁 Overall Migration Finished")
    print(f"   Total Nodes:     {total_stats['nodes']}")
    print(f"   Total Relations: {total_stats['relations']}")
    print(f"   Total Errors:    {total_stats['errors']}")
    print("═"*40)
    
    await store.close()

if __name__ == "__main__":
    asyncio.run(main())
