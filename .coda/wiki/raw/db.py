"""
Coda V4.0 — SurrealDB Storage Adapter
统一存储后端: 桥接 Engine ↔ SurrealDB (startup.ps1 启动的那个)。

当 SurrealDB 可用时, Engine 产生的所有数据 (记忆/知识图谱/追踪/成本)
直接写入旧系统的数据库表, 实现新旧系统数据完全统一。

当 SurrealDB 不可用时, 自动降级为 JSON 文件存储。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, cast, TYPE_CHECKING

if TYPE_CHECKING:
    from surrealdb import AsyncSurreal

logger = logging.getLogger("Coda.db")


class SurrealStore:
    """
    Engine ↔ SurrealDB 存储适配层。

    映射关系:
      SessionMemory → memories 表
      KnowledgeGraph → entities + relations (graph edges)
      SkillFactory → skills 表
      ToolCall → traces 表
      TokenUsage → cost_records 表
      AgentEngine → agents 表 (读取 SOUL 角色)
    """

    _db: Any  # Actually AsyncSurreal but we use Any for runtime flexibility
    _connected: bool
    _config: dict[str, str]

    def __init__(self) -> None:
        self._db = None
        self._connected = False
        self._config = {}

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
        """
        连接到 SurrealDB。

        默认从环境变量读取配置 (与 startup.ps1 和 main.py 共享)。
        """
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
            from surrealdb import AsyncSurreal
            self._db = AsyncSurreal(url)
            db = cast(Any, self._db)
            await db.connect(url)
            await db.signin({"user": user, "pass": password})
            await db.use(namespace, database)
            self._connected = True
            logger.info(f"✅ SurrealStore connected: {url} ({namespace}/{database})")
            return True
        except Exception as e:
            logger.warning(f"SurrealDB unavailable ({e}), using JSON fallback")
            self._connected = False
            return False

    async def disconnect(self) -> None:
        if self._db:
            await cast(Any, self._db).close()
            self._connected = False

    # ════════════════════════════════════════════
    #  Agent SOUL 读取 (按需注入 system prompt)
    # ════════════════════════════════════════════

    async def get_all_agents(self) -> list[dict[str, Any]]:
        """读取 agents 表中所有注册的角色。"""
        if not self._connected:
            return []
        try:
            result = await self._db.query("SELECT * FROM agents ORDER BY type ASC")
            return self._extract_result(result)
        except Exception as e:
            logger.error(f"Failed to read agents: {e}")
            return []

    async def get_agent_by_id(self, agent_id: str) -> dict[str, Any] | None:
        """根据 agent_id 精确查找角色。"""
        if not self._connected or not self._db:
            return None
        try:
            db = cast(Any, self._db)
            result = await db.query(
                "SELECT * FROM agents WHERE id = $id OR name = $name LIMIT 1",
                {"id": agent_id, "name": agent_id},
            )
            rows = self._extract_result(result)
            return rows[0] if rows else None
        except Exception as e:
            logger.error(f"Failed to find agent {agent_id}: {e}")
            return None

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
            result = await self._db.create("memories", data)
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
                await self._db.query(query, {
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
            result = await self._db.query("SELECT * FROM intent_weights")
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
                result = await self._db.query(query, {"vec": query_embedding})
                return self._extract_result(result)
            elif keyword:
                # 关键词退化搜索
                query = (
                    f"SELECT * FROM memories "
                    f"WHERE content.text CONTAINS $kw "
                    f"ORDER BY importance DESC LIMIT {top_k}"
                )
                result = await self._db.query(query, {"kw": keyword})
                return self._extract_result(result)
            else:
                # 最近记忆
                query = f"SELECT * FROM memories ORDER BY created_at DESC LIMIT {top_k}"
                result = await self._db.query(query)
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
            await self._db.upsert(f"entities:{eid}", data)
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
            
            # 格式化 ID (SurrealDB 推荐格式)
            from_id = from_entity if ":" in from_entity else f"entities:{from_entity}"
            to_id = to_entity if ":" in to_entity else f"entities:{to_entity}"
            
            query = f"RELATE {from_id}->{relation_type}->{to_id} CONTENT $data"
            await self._db.query(query, {
                "data": {
                    "weight": 1.0,
                    "source": "wiki_compiler",
                    "properties": properties or {},
                    "created_at": datetime.now().isoformat()
                }
            })
        except Exception as e:
            logger.error(f"Failed to save relation edge: {e}")

    # ════════════════════════════════════════════
    #  KnowledgeNode 专用维护
    # ════════════════════════════════════════════

    async def upsert_knowledge_node(self, node_data: dict[str, Any]) -> str | None:
        """
        全量推送到 SurrealDB。
        node_data 应是通过 KnowledgeNode.to_frontmatter_dict() 生成的。
        """
        if not self._connected:
            return None
        try:
            node_id = node_data.get("id")
            if not node_id: return None
            
            # 清理 ID
            import re
            safe_id = re.sub(r'[^a-zA-Z0-9_]', '_', node_id)
            
            payload = {
                **node_data,
                "updated_at": datetime.now().isoformat()
            }
            
            # 使用 SurrealDB 的 entities 命名空间
            await self._db.upsert(f"entities:{safe_id}", payload)
            return safe_id
        except Exception as e:
            logger.error(f"Failed to upsert knowledge node {node_data.get('id')}: {e}")
            return None

    # ════════════════════════════════════════════
    #  会话与消息 → sessions + messages 表
    # ════════════════════════════════════════════

    async def save_session_messages(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        """同步对话历史到数据库。"""
        if not self._connected:
            return
        try:
            data = {
                "id": session_id,
                "session_id": session_id,
                "messages": messages,
                "updated_at": datetime.now(),
            }
            await self._db.upsert(f"sessions:{session_id}", data)
        except Exception as e:
            logger.debug(f"Failed to sync session {session_id}: {e}")

    async def load_session_messages(self, session_id: str) -> list[dict[str, Any]]:
        """从数据库加载历史消息。"""
        if not self._connected:
            return []
        try:
            result = await self._db.query("SELECT messages FROM sessions WHERE id = $id", {"id": session_id})
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
                "id": traj_id,
                "session_id": session_id,
                "step": step,
                "data": data,
                "created_at": datetime.now(),
            }
            await self._db.create("trajectories", payload)
        except Exception as e:
            logger.warning(f"Failed to log trajectory: {e}")

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
                "created_at": datetime.now(),
            }
            await self._db.create("traces", data)
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
                "created_at": datetime.now(),
            }
            await self._db.create("cost_records", data)
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
                "created_at": datetime.now(),
            }
            await self._db.upsert(f"skills:{sid}", data)
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
            await self._db.create("causal_links", data)
        except Exception as e:
            logger.debug(f"Failed to save causal link: {e}")

    async def load_causal_links(self, limit: int = 100) -> list[dict[str, Any]]:
        """加载历史因果。"""
        if not self._connected:
            return []
        try:
            result = await self._db.query(f"SELECT * FROM causal_links ORDER BY timestamp DESC LIMIT {limit}")
            return self._extract_result(result)
        except Exception as e:
            logger.error(f"Failed to load causal links: {e}")
            return []

    async def load_skills(self) -> list[dict[str, Any]]:
        """从 skills 表加载所有技能。"""
        if not self._connected:
            return []
        try:
            result = await self._db.query("SELECT * FROM skills ORDER BY use_count DESC")
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
            
            # 使用 UPSERT 确保可调整性
            data = {
                **model_data,
                "updated_at": datetime.now(),
            }
            await self._db.upsert(f"models:{safe_id}", data)
            logger.info(f"📋 Model definition persisted to DB: {model_id}")
        except Exception as e:
            logger.error(f"Failed to save model card {model_data.get('model_id')}: {e}")

    async def load_model_cards(self) -> list[dict[str, Any]]:
        """从 models 表加载所有已调整的模型定义。"""
        if not self._connected:
            return []
        try:
            result = await self._db.query("SELECT * FROM models ORDER BY tier ASC, provider ASC")
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
            await self._db.delete(f"models:{safe_id}")
            logger.info(f"🗑️ Model definition deleted from DB: {model_id}")
        except Exception as e:
            logger.error(f"Failed to delete model card {model_id}: {e}")

    # ════════════════════════════════════════════
    #  工具方法
    # ════════════════════════════════════════════

    def _extract_result(self, response: Any) -> list[dict[str, Any]]:
        """从 SurrealDB 响应中提取结果列表 (兼容不同版本)。"""
        if isinstance(response, list) and len(response) > 0:
            first = response[0]
            if isinstance(first, dict) and "result" in first:
                result = first["result"]
                return result if isinstance(result, list) else []
            elif isinstance(first, dict) and "id" in first:
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
