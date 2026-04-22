---
AIGC:
    ContentProducer: Minimax Agent AI
    ContentPropagator: Minimax Agent AI
    Label: AIGC
    ProduceID: "00000000000000000000000000000000"
    PropagateID: "00000000000000000000000000000000"
    ReservedCode1: 304502201df60a0afc2a0f7de2387d437f321be0e505f4d3f5853cf4b019eab4651679d5022100d86c59ad8adc1b7938515b296dfa715217a0fb8d0827a1e97dbeca8b7aa13f10
    ReservedCode2: 3044022017f1778c0cf22c013235787e13083d7c9aa96b58ca83db53b92b82fb518786a6022050fed25ce71fcca976446d799b875659a2d5afb69747df6fc248a800ad23c13b
---

# Knowledge Graph - Retrieval 知识检索

## 角色定义

Retrieval是Knowledge Graph的检索引擎，负责提供多种检索方式，从知识图谱中高效准确地获取所需知识。

## 核心职责

### 1. 检索方式
- **精确检索**: 按ID或属性精确匹配
- **模糊检索**: 近似匹配和拼写纠错
- **向量检索**: 语义相似度检索
- **图遍历**: 基于图的路径检索

### 2. 检索优化
- **查询加速**: 优化检索性能
- **结果排序**: 多维度相关性排序
- **分页处理**: 大结果集分页
- **缓存复用**: 热点结果缓存

### 3. 结果处理
- **结果过滤**: 按条件过滤
- **结果聚合**: 聚合统计
- **结果解释**: 提供检索理由
- **置信度排序**: 按置信度排序

## SurrealDB检索模型

```sql
-- 检索任务
DEFINE TABLE retrieval_tasks SCHEMAFULL;
DEFINE FIELD id ON retrieval_tasks TYPE string;
DEFINE FIELD query_type ON retrieval_tasks TYPE string;
DEFINE FIELD query_params ON retrieval_tasks TYPE object;
DEFINE FIELD filters ON retrieval_tasks TYPE option<object>;
DEFINE FIELD pagination ON retrieval_tasks TYPE object;
DEFINE FIELD results ON retrieval_tasks TYPE option<array>;
DEFINE FIELD execution_time_ms ON retrieval_tasks TYPE int;
DEFINE FIELD created_at ON retrieval_tasks TYPE datetime;

-- 检索历史
DEFINE TABLE retrieval_history SCHEMAFULL;
DEFINE FIELD id ON retrieval_history TYPE string;
DEFINE FIELD query ON retrieval_history TYPE string;
DEFINE FIELD query_type ON retrieval_history TYPE string;
DEFINE FIELD result_count ON retrieval_history TYPE int;
DEFINE FIELD clicked_result ON retrieval_history TYPE option<string>;
DEFINE FIELD user_feedback ON retrieval_history TYPE option<string>;
DEFINE FIELD created_at ON retrieval_tasks TYPE datetime;

-- 索引
DEFINE INDEX idx_history_query ON retrieval_history FIELDS query, created_at DESC;
```

## 检索类型

### 1. 精确检索
```sql
-- 按ID检索
SELECT * FROM entities WHERE id = $id;

-- 按属性检索
SELECT * FROM entities
WHERE type = $type
AND name = $name;

-- 组合条件
SELECT * FROM entities
WHERE type = 'technology'
AND properties.category = 'database'
AND status = 'active';
```

### 2. 模糊检索
```python
async def fuzzy_search(self, query, entity_type=None):
    """模糊搜索"""
    # 使用字符串函数
    search_pattern = f"%{query}%"

    sql = """
        SELECT * FROM entities
        WHERE name CONTAINS $query
    """

    if entity_type:
        sql += " AND type = $entity_type"

    results = await db.query(sql, {"query": query})

    # 进一步过滤和排序
    scored = self.score_fuzzy_results(results, query)

    return sorted(scored, key=lambda x: x["score"], reverse=True)
```

### 3. 向量检索
```sql
-- 语义相似度检索
SELECT
    id,
    name,
    type,
    vector::distance::cosine(embedding, $query_embedding) as similarity
FROM entities
WHERE type = $type
ORDER BY similarity ASC
LIMIT 20;

-- 混合检索
SELECT *,
    vector::distance::cosine(embedding, $query_embedding) as semantic_score
FROM entities
WHERE
    name CONTAINS $keyword
    AND type = $type
ORDER BY
    (CASE WHEN similarity > 0.8 THEN 1.0 ELSE 0.5 END) * (1 - semantic_score) +
    (CASE WHEN name = $keyword THEN 1.0 ELSE 0.0 END)
LIMIT 20;
```

### 4. 图遍历检索
```python
async def graph_traverse(self, start_id, relation_types, max_hops=3):
    """图遍历检索"""
    results = []
    visited = set()

    async def traverse(current_id, depth, path):
        if depth > max_hops:
            return

        relations = await db.query("""
            SELECT * FROM relations
            WHERE from_entity = $id OR to_entity = $id
        """, {"id": current_id})

        for rel in relations:
            next_id = rel.to_entity if rel.from_entity == current_id else rel.from_entity

            if next_id not in visited and rel.type in relation_types:
                visited.add(next_id)
                results.append({
                    "entity": await self.get_entity(next_id),
                    "relation": rel,
                    "path": path + [rel]
                })

                await traverse(next_id, depth + 1, path + [rel])

    await traverse(start_id, 0, [])
    return results
```

## 高级检索

### 多跳检索
```sql
-- 2跳检索: A -> B -> C
SELECT
    e1.id as entity_a,
    e2.id as entity_b,
    e3.id as entity_c
FROM entities e1, relations r1, entities e2, relations r2, entities e3
WHERE e1.id = $start_id
AND r1.from_entity = e1.id AND r1.to_entity = e2.id
AND r2.from_entity = e2.id AND r2.to_entity = e3.id
RETURN {
    start: e1.name,
    middle: e2.name,
    end: e3.name,
    relations: [r1.type, r2.type]
};
```

### 路径发现
```sql
-- 查找最短路径
DEFINE FUNCTION fn::find_shortest_path($start: string, $end: string) {
    -- BFS 查找最短路径
    LET $visited = [];
    LET $queue = [[$start, [$start]]];

    WHILE array::len($queue) > 0 {
        LET $current = $queue[0][0];
        LET $path = $queue[0][1];
        REMOVE $queue[0];

        IF $current = $end {
            RETURN {path: $path, length: array::len($path) - 1};
        }

        LET $relations = SELECT * FROM relations
            WHERE from_entity = $current OR to_entity = $current;

        FOR $rel IN $relations {
            LET $next = ($rel.to_entity IF $rel.from_entity = $current ELSE $rel.from_entity);
            IF $next NOT IN $visited {
                APPEND $next TO $visited;
                APPEND [$next, array::push($path, $next)] TO $queue;
            }
        }
    }

    RETURN null;
};
```

### 子图检索
```sql
-- 围绕某实体的子图
SELECT {
    center: $entity_id,
    entities: (SELECT * FROM entities WHERE id = $entity_id OR id IN [
        SELECT to_entity FROM relations WHERE from_entity = $entity_id
        UNION
        SELECT from_entity FROM relations WHERE to_entity = $entity_id
    ]),
    relations: (SELECT * FROM relations
        WHERE from_entity = $entity_id OR to_entity = $entity_id)
};
```

## 混合检索策略

```python
class HybridRetriever:
    async def hybrid_search(self, query, params):
        """混合检索"""
        results = {
            "keyword": [],
            "vector": [],
            "graph": []
        }

        # 1. 关键词检索
        if params.get("keyword"):
            results["keyword"] = await self.keyword_search(
                params["keyword"],
                params.get("filters")
            )

        # 2. 向量检索
        if params.get("embedding"):
            results["vector"] = await self.vector_search(
                params["embedding"],
                params.get("filters")
            )

        # 3. 图关系检索
        if params.get("related_to"):
            results["graph"] = await self.graph_search(
                params["related_to"],
                params.get("relation_types")
            )

        # 4. 结果融合
        fused = self.fuse_results(results, params.get("weights", {
            "keyword": 0.3,
            "vector": 0.4,
            "graph": 0.3
        }))

        # 5. 重排序
        reranked = await self.rerank(fused, query)

        return reranked
```

## 结果融合

### Reciprocal Rank Fusion
```python
def reciprocal_rank_fusion(self, result_sets, k=60):
    """RRF融合算法"""
    scores = {}

    for result_set in result_sets:
        for rank, item in enumerate(result_set):
            item_id = item["id"]
            # RRF分数
            rrf_score = 1 / (k + rank + 1)

            if item_id not in scores:
                scores[item_id] = {"item": item, "score": 0}

            scores[item_id]["score"] += rrf_score

    # 按分数排序
    sorted_results = sorted(
        scores.values(),
        key=lambda x: x["score"],
        reverse=True
    )

    return [r["item"] for r in sorted_results]
```

### Score Normalization
```python
def normalize_scores(self, results):
    """分数归一化"""
    if not results:
        return results

    max_score = max(r.get("score", 0) for r in results)
    min_score = min(r.get("score", 0) for r in results)

    if max_score == min_score:
        for r in results:
            r["normalized_score"] = 1.0
    else:
        for r in results:
            r["normalized_score"] = (
                (r.get("score", 0) - min_score) / (max_score - min_score)
            )

    return results
```

## 检索结果格式

```json
{
  "retrieval_id": "ret_xxx",
  "timestamp": "2026-03-31T00:15:00Z",
  "query": {
    "text": "SurrealDB",
    "type": "hybrid",
    "params": {
      "filters": {"type": "technology"},
      "weights": {"keyword": 0.3, "vector": 0.7}
    }
  },
  "total_results": 15,
  "results": [
    {
      "id": "entity_001",
      "name": "SurrealDB",
      "type": "technology",
      "score": 0.95,
      "sources": ["keyword", "vector"],
      "excerpt": "A multi-model database...",
      "path": null
    },
    {
      "id": "entity_002",
      "name": "Neo4j",
      "type": "technology",
      "score": 0.82,
      "sources": ["vector"],
      "path": ["SurrealDB", "related_to", "Neo4j"]
    }
  ],
  "execution_time_ms": 45
}
```

## 查询优化

### 查询计划分析
```sql
-- 分析查询计划
EXPLAIN SELECT * FROM entities
WHERE type = 'technology'
AND name CONTAINS 'database'
ORDER BY name;
```

### 索引提示
```python
# 强制使用索引
async def force_index_search(self, field, value):
    """强制使用特定索引"""
    sql = f"USE INDEX idx_{field} SELECT * FROM entities WHERE {field} = $value"
    return await db.query(sql, {"value": value})
```

## 检索缓存

```python
async def cached_search(self, query_params):
    """带缓存的检索"""
    # 生成缓存键
    cache_key = self.generate_cache_key(query_params)

    # 检查缓存
    cached = await cache.get(cache_key)
    if cached:
        return cached

    # 执行检索
    results = await self.search(query_params)

    # 缓存结果
    await cache.set(cache_key, results, ttl=3600)

    return results
```

## 监控与分析

```sql
-- 热门查询
SELECT
    query,
    count(*) as frequency,
    avg(execution_time_ms) as avg_time,
    avg(result_count) as avg_results
FROM retrieval_history
WHERE created_at > time::now() - 7d
GROUP BY query
ORDER BY frequency DESC
LIMIT 20;

-- 零结果查询
SELECT query, count(*) as frequency
FROM retrieval_history
WHERE result_count = 0
GROUP BY query
ORDER BY frequency DESC;
```
