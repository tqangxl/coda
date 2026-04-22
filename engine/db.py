from __future__ import annotations

import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, cast, TYPE_CHECKING, AsyncGenerator

if TYPE_CHECKING:
    from surrealdb import AsyncSurreal

from .base_types import SovereignIdentity # [Phase 1] 循环依赖处理通常较重，直接在此处引用

logger = logging.getLogger("Coda.db")


class SurrealPool:
    """
    SurrealDB 异步连接池 (V7.0)。
    管理多个 AsyncSurreal 实例以支持高并发且不触发 KeyError 竞态。
    """
    def __init__(self, size: int = 5) -> None:
        self.size = size
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        self._conns: list[Any] = []
        self._initialized = False

    async def initialize(self, config: dict[str, str]) -> bool:
        """初始化 N 个连接并放入池中。"""
        try:
            from surrealdb import AsyncSurreal
            for i in range(self.size):
                db = AsyncSurreal(config["url"])
                await db.connect(config["url"])
                await db.signin({"user": config["user"], "pass": config["password"]})
                await db.use(config["namespace"], config["database"])
                await self._queue.put(db)
                self._conns.append(db)
            self._initialized = True
            return True
        except Exception as e:
            logger.error(f"Failed to initialize SurrealPool: {e}")
            await self.close()
            return False

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[Any, None]:
        """借出一个连接供当前协程使用。"""
        conn = await self._queue.get()
        try:
            yield conn
        finally:
            await self._queue.put(conn)

    async def close(self) -> None:
        """关闭所有池连接。"""
        if not self._conns:
            return
        for conn in self._conns:
            try:
                await conn.close()
            except:
                pass
        # 清空队列和连接列表
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._conns.clear()
        self._initialized = False

    async def refresh_connection(self, dead_conn: Any, config: dict[str, str]) -> Any:
        """替换一个已失效的连接。"""
        try:
            from surrealdb import AsyncSurreal
            # 移除旧连接
            if dead_conn in self._conns:
                self._conns.remove(dead_conn)
                try:
                    await dead_conn.close()
                except:
                    pass
            
            # 创建新连接
            new_db = AsyncSurreal(config["url"])
            await new_db.connect(config["url"])
            await new_db.signin({"user": config["user"], "pass": config["password"]})
            await new_db.use(config["namespace"], config["database"])
            
            self._conns.append(new_db)
            return new_db
        except Exception as e:
            logger.error(f"Failed to refresh database connection: {e}")
            return None


class SurrealStore:
    """
    Engine ↔ SurrealDB 存储适配层。
    V7.0 升级版：底层采用 SurrealPool 支持联邦高并发现。
    """

    _pool: SurrealPool | None
    _connected: bool
    _config: dict[str, str]

    def __init__(self, pool_size: int = 5) -> None:
        self._pool = None
        self._pool_size = pool_size
        self._connected = False
        self._config = {}

    async def close(self) -> None:
        """关闭数据库连接池。"""
        if self._pool:
            await self._pool.close()
            self._connected = False
            logger.info("🛑 Database disconnected")

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(
        self,
        url: str | None = None,
        user: str | None = None,
        password: str | None = None,
        namespace: str | None = None,
        database: str | None = None,
    ) -> bool:
        """连接到 SurrealDB (初始化连接池)。"""
        url = url or os.getenv("SURREALDB_URL", "ws://127.0.0.1:11001/rpc")
        user = user or os.getenv("SURREALDB_USER", "root")
        password = password or os.getenv("SURREALDB_PASS", "AgentSecurePass2026")
        namespace = namespace or os.getenv("SURREALDB_NAMESPACE", "ai_agents_v2")
        database = database or os.getenv("SURREALDB_DATABASE", "agent_system")

        self._config = {
            "url": url, "user": user, "password": password,
            "namespace": namespace, "database": database,
        }

        try:
            pool = SurrealPool(size=self._pool_size)
            if await pool.initialize(self._config):
                self._pool = pool
                self._connected = True
                logger.info(f"✅ SurrealStore pool initialized: {url} (Size: {self._pool_size})")
                
                # [V7.0] 自动确保 Wiki Schema 索引就绪
                await self.ensure_wiki_schema()
                return True
            else:
                raise Exception("Pool initialization failed")
        except Exception as e:
            logger.warning(f"SurrealDB unavailable ({e}), using JSON fallback")
            self._connected = False
            return False

    async def disconnect(self) -> None:
        if self._pool:
            await self._pool.close()
            self._connected = False

    async def _safe_query(self, query: str, params: dict[str, Any] | None = None) -> Any:
        """带重试与自愈逻辑的池化查询封装。"""
        if not self._connected or not self._pool:
            return None
        
        max_retries = 3
        for attempt in range(max_retries):
            conn = await self._pool._queue.get()
            try:
                if params:
                    result = await conn.query(query, params)
                else:
                    result = await conn.query(query)
                
                # 成功后将连接归还
                await self._pool._queue.put(conn)
                return result
                
            except Exception as e:
                err_str = str(e).lower()
                # 检测连接是否断开 (Connection closed / no close frame)
                if "no close frame" in err_str or "closed" in err_str or "websocket" in err_str:
                    logger.warning(f"⚠️ Database connection stale (Attempt {attempt+1}), refreshing...")
                    new_conn = await self._pool.refresh_connection(conn, self._config)
                    if new_conn:
                        await self._pool._queue.put(new_conn)
                        await asyncio.sleep(0.2) # 给一点缓冲时间
                        continue
                
                # 如果是 KeyError 或其他可重试错误 (UUID 竞态)
                if isinstance(e, KeyError) and attempt < max_retries - 1:
                    await self._pool._queue.put(conn)
                    logger.debug(f"🔄 Database KeyError race, retrying {attempt+1}...")
                    await asyncio.sleep(0.1)
                    continue
                
                # 其它不可恢复错误，归还连接并抛出
                await self._pool._queue.put(conn)
                if "already exists" in str(e):
                    # 这种错误通常发生在重复定义索引/分析器时，属于正常幂等行为，无需报错
                    return []
                logger.error(f"❌ Database query error: {e}")
                if attempt == max_retries - 1:
                    raise
        return None

    async def execute_query(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """[Public] 执行 SQL 查询。"""
        result = await self._safe_query(query, params)
        return self._extract_result(result)

    async def create_record(self, table: str, data: dict[str, Any]) -> dict[str, Any] | None:
        """[Public] 在指定表中创建记录。"""
        return await self._safe_create(table, data)

    async def upsert_record(self, record_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        """[Public] Upsert 记录。"""
        return await self._safe_upsert(record_id, data)

    async def select_all(self, table: str) -> list[dict[str, Any]]:
        """[Public] 查询表中所有记录。"""
        return await self.execute_query(f"SELECT * FROM {table}")

    async def upsert_identity(self, did: str, data: dict[str, Any]) -> dict[str, Any] | None:
        """[Public] 持久化 Agent 身份。"""
        # DID 转义冒号并加反引号以符合 SurrealDB ID 规范
        safe_did = did.replace(":", "_")
        return await self.upsert_record(f"agent_identity:`{safe_did}`", data)

    async def _safe_create(self, table: str, data: dict[str, Any]) -> Any:
        """带重试逻辑的池化创建封装。"""
        if not self._connected or not self._pool:
            return None
            
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with self._pool.acquire() as db:
                    return await db.create(table, data)
            except KeyError as e:
                if attempt < max_retries - 1:
                    logger.debug(f"🔄 Database KeyError (UUID: {e}), retrying {attempt+1}...")
                    await asyncio.sleep(0.1 * (attempt + 1))
                    continue
                raise

    async def _safe_upsert(self, record: str, data: dict[str, Any]) -> Any:
        """带重试逻辑的池化 Upsert 封装。"""
        if not self._connected or not self._pool:
            return None
            
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with self._pool.acquire() as db:
                    return await db.upsert(record, data)
            except KeyError as e:
                if attempt < max_retries - 1:
                    logger.debug(f"🔄 Database KeyError (UUID: {e}), retrying {attempt+1}...")
                    await asyncio.sleep(0.1 * (attempt + 1))
                    continue
                raise

    # ════════════════════════════════════════════
    #  Agent SOUL 读取 (按需注入 system prompt)
    # ════════════════════════════════════════════

    async def get_all_agents(self) -> list[dict[str, Any]]:
        """读取 agents 表中所有注册的角色。"""
        if not self._connected:
            return []
        try:
            result = await self._safe_query("SELECT * FROM agents ORDER BY type ASC")
            return self._extract_result(result)
        except Exception as e:
            logger.error(f"Failed to read agents: {e}")
            return []

    async def get_agent_by_id(self, agent_id: str) -> dict[str, Any] | None:
        """根据 agent_id 精确查找角色。"""
        if not self._connected or not self._pool:
            return None
        try:
            result = await self._safe_query(
                "SELECT * FROM agents WHERE id = $id OR name = $name LIMIT 1",
                {"id": agent_id, "name": agent_id},
            )
            rows = self._extract_result(result)
            return rows[0] if rows else None
        except Exception as e:
            logger.error(f"Failed to find agent {agent_id}: {e}")
            return None

    # ── Hardened Identity Discovery (PHASE 1: Foundation) ──

    async def identify_agent_did(self, agent_name: str) -> str:
        """
        [PHASE 1] 硬核身份发现：
        从 agent_logs (物理日志) 中检索该 Agent 最近一次签名关联的 DID。
        若无记录，则返回 fallback 虚拟 DID。
        """
        if not self._connected:
            return f"did:agent:virtual:{agent_name}"
            
        try:
            # 搜索 agent_logs 中最近的、带有 DID 元数据的日志
            # 注意: agent_logs 结构在 V7.0 中包含 metadata.did
            query = """
                SELECT metadata.did AS did FROM agent_logs 
                WHERE agent_id = $name AND metadata.did != NONE 
                ORDER BY created_at DESC LIMIT 1
            """
            result = await self._safe_query(query, {"name": agent_name})
            rows = self._extract_result(result)
            
            if rows and rows[0].get("did"):
                return str(rows[0]["did"])
                
            # 兼容性检索: 搜索 agents 表
            agent_data = await self.get_agent_by_id(agent_name)
            if agent_data and agent_data.get("did"):
                return str(agent_data["did"])
                
        except Exception as e:
            logger.warning(f"Identity discovery failed for {agent_name}: {e}")
            
        return f"did:agent:virtual:{agent_name}"

    async def match_agent_for_task(self, task_keywords: list[str]) -> dict[str, Any] | None:
        """
        按需单角色匹配: 根据任务关键词匹配最相关的 Agent 角色。

        匹配策略: 将任务关键词与 agents.capabilities 数组做交集,
        命中最多的角色胜出。零 LLM 调用, 零 API 费用。
        """
        if not self._connected:
            return None
        try:
            agents = await self.get_all_agents()
            if not agents:
                return None

            best_agent: dict[str, Any] | None = None
            best_score = 0

            for agent in agents:
                capabilities = agent.get("capabilities", [])
                if not isinstance(capabilities, list):
                    continue

                # 计算关键词与 capabilities 的交集得分
                score = 0
                cap_text = " ".join(str(c) for c in capabilities).lower()
                name_text = str(agent.get("name", "")).lower()
                type_text = str(agent.get("type", "")).lower()
                summary_text = str(agent.get("metadata", {}).get("summary", "")).lower()

                searchable = f"{cap_text} {name_text} {type_text} {summary_text}"
                for kw in task_keywords:
                    if kw.lower() in searchable:
                        score += 1

                if score > best_score:
                    best_score = score
                    best_agent = agent

            return best_agent if best_score > 0 else None
        except Exception as e:
            logger.error(f"Agent matching failed: {e}")
            return None

    # ════════════════════════════════════════════
    #  记忆 → memories 表
    # ════════════════════════════════════════════

    async def save_memory(
        self,
        content: str,
        category: str = "general",
        importance: float = 0.5,
        embedding: list[float] | None = None,
        tags: list[str] | None = None,
    ) -> str | None:
        """保存一条记忆到 memories 表。"""
        if not self._connected:
            return None
        try:
            data: dict[str, Any] = {
                "type": category,
                "content": {
                    "text": content,
                    "embedding": embedding or [],
                },
                "tags": tags or [category],
                "importance": importance,
                "access_count": 0,
                "last_accessed": datetime.now(),
                "created_at": datetime.now(),
            }
            result = await self._safe_create("memories", data)
            mem_id = result.get("id", "") if isinstance(result, dict) else ""
            return str(mem_id)
        except Exception as e:
            logger.error(f"Failed to save memory: {e}")
            return None

    # ════════════════════════════════════════════
    #  认知权重 → intent_weights 表 (Pillar 42)
    # ════════════════════════════════════════════

    async def save_intent_weights(self, weights: dict[str, float]) -> None:
        """将意图权重持久化到 SurrealDB (含 JSON 降级支持)。"""
        if not self._connected:
            # Pillar 26: 自动降级为 JSON 存储
            self._save_weights_to_json(weights)
            return
        try:
            # 使用 upsert 逻辑: 如果存在则更新，不存在则创建
            count = 0
            for intent, weight in weights.items():
                if not intent: continue
                # Sanitization: Ensure record ID is valid surrealdb ID
                import re
                intent_id = re.sub(r'[^a-zA-Z0-9]', '_', intent).lower().strip('_')
                if not intent_id: intent_id = "default"
                
                # Pillar 26: 认知持久化 - 原生 UPSERT 语句确保原子性
                query = f"UPSERT intent_weights:{intent_id} SET intent = $intent, weight = $weight, updated_at = $now"
                await self._safe_query(query, {
                    "intent": intent, 
                    "weight": float(weight), 
                    "now": datetime.now().isoformat()
                })
                count += 1
            
            if count > 0:
                logger.info(f"🧠 Cognitive weights persisted to DB: {count} entries.")
        except Exception as e:
            logger.error(f"Failed to save intent weights to DB: {e}")
            # 失败后尝试降级
            self._save_weights_to_json(weights)

    async def load_intent_weights(self) -> dict[str, float]:
        """加载权重: 优先 DB, 失败则回退 JSON。"""
        if not self._connected:
            return self._load_weights_from_json()
        try:
            result = await self._safe_query("SELECT * FROM intent_weights")
            rows = self._extract_result(result)
            loaded = {str(row["intent"]): float(row["weight"]) for row in rows if "intent" in row and "weight" in row}
            if loaded:
                logger.info(f"🧠 Successfully loaded {len(loaded)} weights from DB.")
            return loaded
        except Exception as e:
            logger.warning(f"Failed to load weights from DB: {e}, falling back to JSON")
            return self._load_weights_from_json()

    async def search_memories(
        self,
        query_embedding: list[float] | None = None,
        keyword: str = "",
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        搜索记忆。

        优先使用向量搜索 (如有 embedding), 退化为关键词搜索。
        """
        if not self._connected:
            return []
        try:
            if query_embedding and len(query_embedding) > 0:
                # 向量搜索 — 利用 SurrealDB MTREE 索引
                # 注: SurrealDB 的向量搜索语法可能因版本而异
                query = (
                    f"SELECT *, vector::similarity::cosine(content.embedding, $vec) AS score "
                    f"FROM memories "
                    f"WHERE vector::similarity::cosine(content.embedding, $vec) > 0.3 "
                    f"ORDER BY score DESC LIMIT {top_k}"
                )
                result = await self._safe_query(query, {"vec": query_embedding})
                return self._extract_result(result)
            elif keyword:
                # 关键词退化搜索
                query = (
                    f"SELECT * FROM memories "
                    f"WHERE content.text CONTAINS $kw "
                    f"ORDER BY importance DESC LIMIT {top_k}"
                )
                result = await self._safe_query(query, {"kw": keyword})
                return self._extract_result(result)
            else:
                # 最近记忆
                query = f"SELECT * FROM memories ORDER BY created_at DESC LIMIT {top_k}"
                result = await self._safe_query(query)
                return self._extract_result(result)
        except Exception as e:
            logger.error(f"Memory search failed: {e}")
            return []

    # ════════════════════════════════════════════
    #  知识图谱 → entities + relations 表
    # ════════════════════════════════════════════

    async def save_entity(
        self,
        name: str,
        entity_type: str,
        properties: dict[str, str] | None = None,
        embedding: list[float] | None = None,
    ) -> str | None:
        """保存实体到 entities 表。"""
        if not self._connected:
            return None
        try:
            import hashlib
            eid = hashlib.md5(f"{entity_type}:{name}".encode()).hexdigest()[:12]
            data: dict[str, Any] = {
                "id": eid,
                "name": name,
                "type": entity_type,
                "properties": properties or {},
                "embedding": embedding or [],
                "created_at": datetime.now(),
            }
            await self._safe_upsert(f"entities:{eid}", data)
            return eid
        except Exception as e:
            logger.error(f"Failed to save entity: {e}")
            return None

    async def save_relation(
        self,
        from_entity: str,
        to_entity: str,
        relation_type: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """
        保存关系。
        如果 DB 支持图模型, 则使用 RELATE 语法创建 Edge; 否则降级为关系表。
        """
        if not self._connected:
            return
        try:
            # SurrealDB Graph Edge 语法: RELATE entity:a -> depends_on -> entity:b
            # 我们使用更兼容的 upsert 模式，同时保留关系 ID 以便幂等
            import hashlib
            rid = hashlib.md5(f"{from_entity}:{relation_type}:{to_entity}".encode()).hexdigest()[:12]
            def parse_entity(entity_str: str) -> tuple[str, str | list[str]]:
                if ":" in entity_str:
                    tb, sid = entity_str.split(":", 1)
                    if (sid.startswith("[") and sid.endswith("]")) or (sid.startswith("'") and sid.endswith("'")):
                        # 处理形如 ['proj', 'id'] 的复合键
                        try:
                            import ast
                            return tb, ast.literal_eval(sid)
                        except:
                            return tb, sid
                    return tb, sid
                return "entities", entity_str

            from_tb, from_sid = parse_entity(from_entity)
            to_tb, to_sid = parse_entity(to_entity)

            # V7.2: SurrealDB 3.x 禁止在 RELATE 中直接使用函数调用。
            # 使用 LET 预绑定 Record ID，再在 RELATE 中引用绑定变量。
            data_payload = {
                "weight": 1.0,
                "source": "wiki_compiler",
                "properties": properties or {},
                "created_at": datetime.now().isoformat()
            }
            query = (
                f"LET $__from = type::record($from_tb, $from_sid); "
                f"LET $__to = type::record($to_tb, $to_sid); "
                f"RELATE $__from->{relation_type}->$__to CONTENT $data"
            )
            await self._safe_query(query, {
                "from_tb": from_tb,
                "from_sid": from_sid,
                "to_tb": to_tb,
                "to_sid": to_sid,
                "data": data_payload,
            })

            # [PHASE 1] Relation Audit Logging: 物理审计轨迹集成
            await self.log_agent_action(
                agent_id="wiki_compiler",
                action_type="PHYSICAL_LINK",
                target=f"{from_entity} -> {to_entity}",
                metadata={
                    "relation_type": relation_type,
                    "context": "Knowledge Graph Construction",
                    "properties": properties
                }
            )
        except Exception as e:
            logger.error(f"Failed to save relation edge: {e}")

    # ════════════════════════════════════════════
    #  KnowledgeNode 专用维护
    # ════════════════════════════════════════════

    async def upsert_knowledge_node(self, node_data: dict[str, Any]) -> str | None:
        """
        将知识节点全量推送到 SurrealDB。
        
        使用复合 Record ID: wiki_nodes:[project_id, node_id]
        确保不同项目的节点物理隔离且支持跨项目图谱查询。
        """
        if not self._connected:
            return None
        try:
            node_id = node_data.get("id")
            project_id = node_data.get("project_id", "default")
            if not node_id:
                return None

            # 使用 SurrealDB array record ID 实现复合键: wiki_nodes:[project_id, node_id]
            # 不同项目的相同 node_id 将存储在不同的 record 中
            # 从 payload 移除 'id' 字段
            # 原因: SurrealDB 在指定 array record ID 时，payload 里不能再含 id，否则报冲突
            payload = {k: v for k, v in node_data.items() if k != "id"}
            payload["project_id"] = project_id
            payload["updated_at"] = datetime.now().isoformat()

            # SurrealDB 数组 ID 格式: wiki_nodes:["project_id", "node_id"]
            # V7.1 Hardening: 使用 table:[$pid, $nid] 语法，这是最兼容的 Record ID 参数化方式
            query = "UPSERT wiki_nodes:[$pid, $nid] MERGE $payload"
            await self._safe_query(
                query,
                {"pid": project_id, "nid": node_id, "payload": payload}
            )
            return node_id
        except Exception as e:
            logger.error(f"Failed to upsert knowledge node {node_data.get('id')}: [{type(e).__name__}] {e}")
            return None
        
    async def save_session_report(self, session_id: str, summary: str, tasks: list[str] | None = None) -> str | None:
        """
        [V7.1] 将会话摘要“结晶化”存入数据库。
        转换流式对话记录为持久化的知识节点。
        """
        if not self._connected:
            return None
        
        node_data = {
            "id": f"session-{session_id}",
            "title": f"Session Summary: {session_id}",
            "type": "session_report",
            "status": "validated",
            "confidence": 1.0,
            "body": summary,
            "tags": ["session", "learning", "archive"],
            "tasks": tasks or [],
            "project_id": "system_logs",
            "layer": 3  # 归档层
        }
        return await self.upsert_knowledge_node(node_data)

    async def get_wiki_node(self, project_id: str, node_id: str) -> dict[str, Any] | None:
        """获取单个知识节点的完整数据。"""
        if not self._connected:
            return None
        try:
            clean_pid = project_id.replace("\\", "\\\\").replace("'", "\\'")
            clean_nid = node_id.replace("\\", "\\\\").replace("'", "\\'")
            record_id = f"wiki_nodes:['{clean_pid}', '{clean_nid}']"
            res = await self._safe_query(
                f"SELECT * FROM {record_id} WHERE expires_at IS NONE OR expires_at > time::unix()"
            )
            rows = self._extract_result(res)
            return rows[0] if rows else None
        except Exception as e:
            logger.error(f"Failed to get wiki node {node_id}: {e}")
            return None

    async def ensure_wiki_schema(self) -> None:
        """
        确保 wiki_nodes 表的 FTS 和向量索引已定义。
        [进阶增强]: 支持中英文混合检索，采用 Class 分词策略。
        """
        if not self._connected:
            return
        try:
            # 1. 定义分析器
            await self._safe_query("DEFINE ANALYZER wiki_analyzer TOKENIZERS blank, class, camel, punct FILTERS lowercase, ascii, snowball(english);")
            await self._safe_query("DEFINE ANALYZER cjk_ngram TOKENIZERS class FILTERS lowercase, edgengram(1, 4);")

            # 2. 定义 FTS 索引 (SurrealDB 3.0+ 语法: FULLTEXT ANALYZER)
            # 关键: 3.0.5 版本 FULLTEXT 索引仅支持单字段，多字段需拆分
            try:
                await self._safe_query("DEFINE INDEX node_fts_title ON wiki_nodes FIELDS title FULLTEXT ANALYZER wiki_analyzer;")
                await self._safe_query("DEFINE INDEX node_fts_body ON wiki_nodes FIELDS body FULLTEXT ANALYZER wiki_analyzer;")
            except Exception as e:
                if "already exists" not in str(e).lower():
                    logger.warning(f"FTS index fallback: {e}")
                try:
                    await self._safe_query("DEFINE INDEX node_fts_simple ON wiki_nodes FIELDS title, body;")
                except: pass
            
            try:
                await self._safe_query("DEFINE INDEX node_fuzzy ON wiki_nodes FIELDS title FULLTEXT ANALYZER cjk_ngram;")
            except Exception as e:
                if "already exists" not in str(e).lower():
                    logger.warning(f"Fuzzy index fallback: {e}")
                try:
                    await self._safe_query("DEFINE INDEX node_fuzzy ON wiki_nodes FIELDS title;")
                except: pass
            
            # 3. 预定义所有 AKP 关系表 (避免 SELECT 时报错)
            rel_types = [
                "refers_to", "depends_on", "contradicts", "extends", "SIMILAR_TO",
                "supersedes", "grounds", "implies", "tensions_with", "part_of",
                "related_to", "mentions", "implements", "manages", "validates"
            ]
            for rt in rel_types:
                try:
                    # 定义为关系表 (Edge)
                    await self._safe_query(f"DEFINE TABLE {rt} TYPE RELATION;")
                except:
                    pass

            # 4. 定义辅助索引
            await self._safe_query("DEFINE INDEX node_project_idx ON wiki_nodes FIELDS project_id;")
            await self._safe_query("DEFINE INDEX node_updated_idx ON wiki_nodes FIELDS updated_at;")
            await self._safe_query("DEFINE INDEX node_pinyin_idx ON wiki_nodes FIELDS [pinyin_title, pinyin_abbr];")
            
            logger.info("🛠️ SurrealDB ultra-advanced wiki schema (Pinyin + CJK) verified.")
        except Exception as e:
            # 这里的 e 包含 "already exists" 等，日志级别下调
            if "already exists" not in str(e):
                logger.debug(f"Wiki schema setup notice: {e}")

    async def delete_knowledge_node(self, project_id: str, node_id: str) -> bool:
        """从 SurrealDB 中物理移除知识节点及其关联记录。"""
        if not self._connected:
            return False
        try:
            # 联邦 Record ID: wiki_nodes:['project_id', 'node_id']
            query = "DELETE wiki_nodes:[$pid, $nid]"
            await self._safe_query(query, {"pid": project_id, "nid": node_id})
            logger.info(f"🗑️ Deleted knowledge node: wiki_nodes:['{project_id}', '{node_id}']")
            return True
        except Exception as e:
            logger.error(f"Failed to delete knowledge node {node_id} from {project_id}: [{type(e).__name__}] {e}")
            return False

    # ════════════════════════════════════════════
    #  联邦挂载 → mounts 表 (V7.0)
    # ════════════════════════════════════════════

    async def add_mount(
        self,
        subscriber: str,
        upstream: str,
        access: str = "readonly",
    ) -> bool:
        """
        注册挂载关系: subscriber 订阅 upstream 的知识库。
        access: 'readonly' | 'readwrite'
        """
        if not self._connected:
            return False
        try:
            import hashlib
            mount_id = hashlib.md5(f"{subscriber}:{upstream}".encode()).hexdigest()[:12]
            # SurrealDB 在写入不存在的表时会自动以 SCHEMALESS 模式创建
            # 使用 type::record() 语法传递 param 作为 record ID
            await self._safe_query(
                "UPSERT type::record('mounts', $id) SET subscriber=$sub, upstream=$up, access=$acc, created_at=$ts",
                {
                    "id": mount_id,
                    "sub": subscriber,
                    "up": upstream,
                    "acc": access,
                    "ts": datetime.now().isoformat(),
                }
            )
            logger.info(f"✅ Mount registered: {subscriber} → {upstream} ({access})")
            return True
        except Exception as e:
            logger.error(f"Failed to add mount {subscriber}->{upstream}: {e}")
            return False

    async def remove_mount(self, subscriber: str, upstream: str) -> bool:
        """Remove a mount (unsubscribe)."""
        if not self._connected:
            return False
        try:
            await self._safe_query(
                "DELETE mounts WHERE subscriber = $sub AND upstream = $up",
                {"sub": subscriber, "up": upstream}
            )
            return True
        except Exception as e:
            logger.error(f"Failed to remove mount: {e}")
            return False

    async def get_visible_scope(self, project_id: str) -> list[str]:
        """
        获取当前项目可见的所有项目 ID 列表。
        = 自身 + 所有已挂载的上游库。
        """
        if not self._connected:
            return [project_id]
        try:
            result = await self._safe_query(
                "SELECT upstream FROM mounts WHERE subscriber = $pid",
                {"pid": project_id}
            )
            rows = self._extract_result(result)
            upstreams = [r["upstream"] for r in rows if "upstream" in r]
            return [project_id] + upstreams
        except Exception as e:
            err = str(e)
            # mounts 表尚未创建时属正常情况, 返回仅包含自身的范围
            if "does not exist" in err or "table" in err.lower():
                return [project_id]
            logger.error(f"Failed to get visible scope for {project_id}: {e}")
            return [project_id]

    async def federated_search_nodes(
        self,
        project_id: str,
        keyword: str = "",
        query_embedding: list[float] | None = None,
        layer_filter: list[int] | None = None,
        limit: int = 20,
        weights: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        """
        [V7.0] 联邦 4D 混合搜索:
          - Semantic (Vector similarity)
          - Keyword (FTS BM25)
          - Temporal (Recency decay)
          - Relational (Graph density via subquery)
        """
        if not self._connected:
            return []
        
        try:
            scope = await self.get_visible_scope(project_id)
            w = weights or {"sem": 0.4, "fts": 0.3, "temp": 0.15, "rel": 0.15}

            # 构建 SurrealQL 混合查询
            # 1. 向量相似度 (如果有)
            vec_score = "0.0"
            if query_embedding and len(query_embedding) > 0:
                vec_score = "vector::similarity::cosine(embedding, $vec)"

            # 2. FTS + Pinyin 分数 (多维融合)
            fts_cond = ""
            fts_score = "0.0"
            if keyword:
                # 组合主分析器检索、N-gram 模糊检索、以及拼音检索 (全拼或首字母)
                # search::score(1): node_fts, search::score(2): node_fuzzy
                # 我们同时检查 pinyin_title 和 pinyin_abbr 字段
                fts_cond = """
                AND ( 
                    (title, body) MATCHES $kw 
                    OR title MATCHES $kw 
                    OR pinyin_title CONTAINS $kw_low 
                    OR pinyin_abbr CONTAINS $kw_low
                )
                """
                # 评分加权: 词法(0.6) + 模糊(0.2) + 拼音(0.2)
                # 注意: pinyin CONTAINS 是布尔值，我们将其映射为分数
                fts_score = """
                (search::score(1) * 0.6 + search::score(2) * 0.2 + 
                 (if pinyin_title CONTAINS $kw_low OR pinyin_abbr CONTAINS $kw_low then 0.2 else 0.0 end))
                """

            # 3. 时间衰减 (Recency)
            # ...

            # 3. 时间衰减 (Recency)
            # 简化版：1.0 / (1.0 + (now - updated_at) / day)
            temp_score = "1.0 / (1.0 + (math::abs(time::now() - updated_at) / 1d))"

            # 4. 关系密度 (Relational)
            # 通过子查询统计入边和出边
            rel_score = "(count(->?) + count(<-?)) / 10.0"

            # 组装层级过滤
            layer_clause = ""
            if layer_filter is not None:
                layers_str = ", ".join(str(l) for l in layer_filter)
                layer_clause = f" AND layer IN [{layers_str}]"

            # 最终混合查询 (Weighted Fusion)
            # [V7.1] 自动过滤过期 (TTL) 的知识节点
            query = f"""
            SELECT *, 
                id as node_id,
                ({w['sem']} * {vec_score} + 
                 {w['fts']} * {fts_score} + 
                 {w['temp']} * {temp_score} + 
                 {w['rel']} * {rel_score} + 
                 (if memory_horizon = 'long_term' then 0.5 else 0.0 end) ) AS hybrid_score
            FROM wiki_nodes 
            WHERE project_id IN $scope 
              AND (expires_at IS NONE OR expires_at > time::unix())
              {fts_cond} {layer_clause}
            ORDER BY hybrid_score DESC 
            LIMIT $limit;
            """

            params = {
                "scope": scope,
                "kw": keyword,
                "vec": query_embedding or [],
                "limit": limit
            }

            result = await self._safe_query(query, params)
            return self._extract_result(result)

        except Exception as e:
            logger.error(f"Federated hybrid search failed: {e}")
            # Fallback to basic search if hybrid fails (e.g. index not ready)
            try:
                scope = await self.get_visible_scope(project_id)
                query = f"SELECT * FROM wiki_nodes WHERE project_id IN $scope AND body CONTAINS $kw LIMIT $limit"
                result = await self._safe_query(query, {"scope": scope, "kw": keyword, "limit": limit})
                return self._extract_result(result)
            except:
                return []


    # ════════════════════════════════════════════
    #  会话与消息 → sessions + messages 表
    # ════════════════════════════════════════════

    async def save_session_messages(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        """同步对话历史到数据库。"""
        if not self._connected:
            return
        try:
            data = {
                "id": f"sessions:{session_id}",
                "session_id": session_id,
                "messages": messages,
                "updated_at": datetime.now().isoformat(),
            }
            await self._safe_upsert(f"sessions:{session_id}", data)
        except Exception as e:
            logger.debug(f"Failed to sync session {session_id}: {e}")

    async def load_session_messages(self, session_id: str) -> list[dict[str, Any]]:
        """从数据库加载历史消息。"""
        if not self._connected:
            return []
        try:
            result = await self._safe_query("SELECT messages FROM sessions WHERE id = $id", {"id": session_id})
            rows = self._extract_result(result)
            return rows[0].get("messages", []) if rows else []
        except Exception as e:
            logger.error(f"Failed to load session messages: {e}")
            return []

    # ════════════════════════════════════════════
    #  轨迹 → trajectories 表
    # ════════════════════════════════════════════

    async def log_trajectory(self, session_id: str, step: int, data: dict[str, Any]) -> None:
        """将结构化轨迹同步到数据库。"""
        if not self._connected:
            return
        try:
            traj_id = f"traj_{session_id}_{step:03d}"
            payload = {
                "id": f"trajectories:{traj_id}",
                "session_id": session_id,
                "step": step,
                "data": data,
                "created_at": datetime.now().isoformat(),
            }
            await self._safe_create("trajectories", payload)
        except Exception as e:
            logger.warning(f"Failed to log trajectory: {e}")

    # ── Agent Audit Logs (PHASE 1: Foundation) ──

    async def log_agent_action(
        self,
        agent_id: str,
        action_type: str,
        target: str,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None
    ) -> None:
        """
        [PHASE 1] 物理审计日志：
        记录 Agent 的关键物理动作（如：建立链接、执行指令、跨库操作）。
        这是满足 HTAS 审计要求的“硬记忆”。
        """
        if not self._connected:
            return
        try:
            import uuid
            log_id = str(uuid.uuid4())[:12]
            data = {
                "id": f"agent_logs:{log_id}",
                "agent_id": agent_id,
                "action": action_type,
                "target": target,
                "metadata": metadata or {},
                "session_id": session_id,
                "created_at": datetime.now().isoformat()
            }
            # 使用 _safe_query 运行 UPSERT 或 CREATE
            await self._safe_query("CREATE agent_logs CONTENT $data", {"data": data})
        except Exception as e:
            logger.warning(f"Failed to log agent action: {e}")

    # ════════════════════════════════════════════
    #  追踪 → traces 表
    # ════════════════════════════════════════════

    async def log_trace(
        self,
        operation_name: str,
        agent_id: str,
        status: str = "ok",
        duration_ms: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """记录工具调用追踪到 traces 表。"""
        if not self._connected:
            return
        try:
            import uuid
            data: dict[str, Any] = {
                "id": str(uuid.uuid4())[:8],
                "operation_name": operation_name,
                "agent_id": agent_id,
                "status": status,
                "duration_ms": duration_ms,
                "metadata": metadata or {},
                "created_at": datetime.now().isoformat(),
            }
            await self._safe_create("traces", data)
        except Exception as e:
            logger.warning(f"Failed to log trace: {e}")  # 追踪失败不应阻断主流程

    # ════════════════════════════════════════════
    #  成本 → cost_records 表
    # ════════════════════════════════════════════

    async def log_cost(
        self,
        agent_id: str,
        task_id: str,
        cost_type: str,
        quantity: float,
        unit_price: float,
        total_cost: float,
    ) -> None:
        """记录 Token 消费到 cost_records 表。"""
        if not self._connected:
            return
        try:
            import uuid
            data: dict[str, Any] = {
                "id": str(uuid.uuid4())[:8],
                "agent_id": agent_id,
                "task_id": task_id,
                "cost_type": cost_type,
                "quantity": quantity,
                "unit_price": unit_price,
                "total_cost": total_cost,
                "created_at": datetime.now().isoformat(),
            }
            await self._safe_create("cost_records", data)
        except Exception as e:
            logger.warning(f"Failed to log cost: {e}")

    # ════════════════════════════════════════════
    #  技能 → skills 表
    # ════════════════════════════════════════════

    async def save_skill(
        self,
        name: str,
        description: str,
        trigger: list[str],
        workflow: dict[str, Any],
    ) -> None:
        """保存自动生成的技能到 skills 表。"""
        if not self._connected:
            return
        try:
            import hashlib
            sid = hashlib.md5(name.encode()).hexdigest()[:8]
            data: dict[str, Any] = {
                "id": sid,
                "name": name,
                "description": description,
                "version": "1.0",
                "trigger": trigger,
                "tools": [],
                "workflow": workflow,
                "rating": 0.0,
                "use_count": 0,
                "created_at": datetime.now().isoformat(),
            }
            await self._safe_upsert(f"skills:{sid}", data)
        except Exception as e:
            logger.error(f"Failed to save skill: {e}")

    # ════════════════════════════════════════════
    #  因果链 → causal_links 表
    # ════════════════════════════════════════════

    async def save_causal_link(self, data: dict[str, Any]) -> None:
        """保存因果三元组。"""
        if not self._connected:
            return
        try:
            await self._safe_create("causal_links", data)
        except Exception as e:
            logger.debug(f"Failed to save causal link: {e}")

    async def load_causal_links(self, limit: int = 100) -> list[dict[str, Any]]:
        """加载历史因果。"""
        if not self._connected:
            return []
        try:
            result = await self._safe_query(f"SELECT * FROM causal_links ORDER BY timestamp DESC LIMIT {limit}")
            return self._extract_result(result)
        except Exception as e:
            logger.error(f"Failed to load causal links: {e}")
            return []

    async def load_skills(self) -> list[dict[str, Any]]:
        """从 skills 表加载所有技能。"""
        if not self._connected:
            return []
        try:
            result = await self._safe_query("SELECT * FROM skills ORDER BY use_count DESC")
            return self._extract_result(result)
        except Exception as e:
            logger.error(f"Failed to load skills: {e}")
            return []


    # ════════════════════════════════════════════
    #  模型注册表 → models 表 (V6.2 Adjustability)
    # ════════════════════════════════════════════

    async def save_model_card(self, model_data: dict[str, Any]) -> None:
        """保存模型配置到 models 表。"""
        if not self._connected:
            return
        try:
            model_id = model_data.get("model_id")
            if not model_id:
                return
            
            # Sanitization for DB ID: SurrealDB ID 建议不带中划线以防解析为减法
            import re
            safe_id = re.sub(r'[^a-zA-Z0-9_]', '_', model_id)
            
            # 使用 UPSERT 确保可调整性 (带池化重试)
            data = {
                **model_data,
                "updated_at": datetime.now().isoformat(),
            }
            await self._safe_upsert(f"models:{safe_id}", data)
            logger.info(f"📋 Model definition persisted to DB: {model_id}")
        except Exception as e:
            logger.error(f"Failed to save model card {model_data.get('model_id')}: {e}")

    async def load_model_cards(self) -> list[dict[str, Any]]:
        """从 models 表加载所有已调整的模型定义。"""
        if not self._connected:
            return []
        try:
            result = await self._safe_query("SELECT * FROM models ORDER BY tier ASC, provider ASC")
            return self._extract_result(result)
        except Exception as e:
            logger.error(f"Failed to load model cards from DB: {e}")
            return []

    async def delete_model_card(self, model_id: str) -> None:
        """从 models 表删除指定模型定义。"""
        if not self._connected:
            return
        try:
            import re
            safe_id = re.sub(r'[^a-zA-Z0-9_]', '_', model_id)
            if self._connected and self._pool:
                async with self._pool.acquire() as db:
                    await db.delete(f"models:{safe_id}")
            logger.info(f"🗑️ Model definition deleted from DB: {model_id}")
        except Exception as e:
            logger.error(f"Failed to delete model card {model_id}: {e}")

    # ════════════════════════════════════════════
    #  工具方法
    # ════════════════════════════════════════════

    # ── [Phase 3] Federated Graph Walk (V7.0) ──
    async def federated_graph_walk(
        self,
        start_nodes: list[str],
        project_id: str = "default",
        max_hops: int = 2,
        limit: int = 20
    ) -> list[dict[str, Any]]:
        """
        跨层级图谱遍历: 从起始节点出发，沿关系链探索深度相关知识。
        利用 SurrealDB 的图查询能力：SELECT ->rel->wiki_nodes
        """
        if not self._connected or not start_nodes:
            return []
        
        try:
            # [V7.1] 安全的图谱遍历方案: 先提取 ID 集合
            query = """
                LET $starts = (SELECT id FROM wiki_nodes WHERE project_id = $pid AND id INSIDE $node_ids);
                SELECT *, 
                    (SELECT id, title, node_type FROM ->?->wiki_nodes WHERE id NOT INSIDE $starts LIMIT 5) as neighbors
                FROM $starts
                LIMIT $limit;
            """
            res = await self._safe_query(query, {
                "pid": project_id,
                "node_ids": start_nodes,
                "limit": limit
            })
            return self._extract_result(res)
        except Exception as e:
            logger.error(f"Graph walk failed: {e}")
            return []

    async def discover_by_facts(self, fact_keywords: list[str], limit: int = 10) -> list[dict[str, Any]]:
        """
        事实锚定发现: 寻找包含特定事实模式的节点，揭示隐性关联。
        """
        if not self._connected:
            return []
        try:
            # 寻找标记为 SYNTHESIS/FACT 且 body 包含特定关键词的节点
            keywords_regex = "|".join(fact_keywords)
            query = "SELECT * FROM wiki_nodes WHERE node_type = 'synthesis' AND body ~ $regex LIMIT $limit"
            res = await self._safe_query(query, {"regex": keywords_regex, "limit": limit})
            return self._extract_result(res)
        except Exception as e:
            logger.error(f"Fact discovery failed: {e}")
            return []

    def _extract_result(self, response: Any) -> list[dict[str, Any]]:
        """从 SurrealDB 响应中提取结果列表 (兼容不同版本)。"""
        if isinstance(response, list) and len(response) > 0:
            first = response[0]
            if isinstance(first, dict):
                # If it's a wrapper like {'result': [...], 'status': 'OK', 'time': ...}
                if "result" in first and "time" in first:
                    result = first["result"]
                    return result if isinstance(result, list) else []
                # Otherwise, it's likely just a list of row dicts
                return response  # type: ignore
            elif isinstance(first, list):
                return first
        elif isinstance(response, dict) and "result" in response:
            result = response["result"]
            return result if isinstance(result, list) else []
        return []

    # ════════════════════════════════════════════
    #  JSON Fallback 逻辑 (Pillar 26)
    # ════════════════════════════════════════════

    def _save_weights_to_json(self, weights: dict[str, float]) -> None:
        """当 DB 不可用时, 保存权重到本地 JSON。"""
        try:
            import json
            path = os.path.join(os.getcwd(), "intent_weights.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(weights, f, ensure_ascii=False, indent=2)
            logger.info(f"💾 Cognitive weights saved to JSON: {path}")
        except Exception as e:
            logger.error(f"Failed to save weights to JSON: {e}")

    def _load_weights_from_json(self) -> dict[str, float]:
        """从本地 JSON 加载权重。"""
        try:
            import json
            path = os.path.join(os.getcwd(), "intent_weights.json")
            if not os.path.exists(path):
                return {}
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info(f"💾 Loaded weights from JSON: {len(data)} entries.")
            return {str(k): float(v) for k, v in data.items()}
        except Exception as e:
            logger.warning(f"Failed to load weights from JSON: {e}")
            return {}
