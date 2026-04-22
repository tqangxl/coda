# MemoryKeeper Agent - Agent配置

## 基本信息

```yaml
agent:
  id: "memory-keeper"
  name: "MemoryKeeper"
  type: "memory"
  version: "2.0.0"
  namespace: "ai_agents_v2"
```

## 职责

- 记忆管理与持久化
- 上下文智能注入
- 知识图谱维护

## cx优化配置

```yaml
cx_config:
  enabled: true

  before_llm_call:
    - command: "symbols"
      reason: "了解检索需求"
```

## 记忆分类

```yaml
memory:
  classification:
    short_term:
      ttl: "24h"
      storage: "memories_short"
    medium_term:
      ttl: "7d"
      storage: "memories_medium"
    long_term:
      ttl: "30d"
      storage: "memories_long"

  principles:
    - "用户偏好进记忆"
    - "代码内容不进记忆"
    - "敏感信息加密存储"
```

## SurrealDB表

```sql
-- MemoryKeeper专用表
DEFINE TABLE memories SCHEMAFULL;
DEFINE FIELD id ON memories TYPE string;
DEFINE FIELD agent_id ON memories TYPE string;
DEFINE FIELD memory_type ON memories TYPE string;
DEFINE FIELD content ON memories TYPE object;
DEFINE FIELD importance ON memories TYPE float DEFAULT 0.5;
DEFINE FIELD access_count ON memories TYPE int DEFAULT 0;
DEFINE FIELD created_at ON memories TYPE datetime DEFAULT time::now();
DEFINE FIELD last_accessed ON memories TYPE datetime;

DEFINE TABLE knowledge_graph SCHEMAFULL;
DEFINE FIELD id ON knowledge_graph TYPE string;
DEFINE FIELD entity_type ON knowledge_graph TYPE string;
DEFINE FIELD entity_name ON knowledge_graph TYPE string;
DEFINE FIELD properties ON knowledge_graph TYPE object;
DEFINE FIELD embedding ON knowledge_graph TYPE array<float>;
DEFINE FIELD created_at ON knowledge_graph TYPE datetime DEFAULT time::now();

DEFINE TABLE relations SCHEMAFULL;
DEFINE FIELD id ON relations TYPE string;
DEFINE FIELD from_entity ON relations TYPE string;
DEFINE FIELD to_entity ON relations TYPE string;
DEFINE FIELD relation_type ON relations TYPE string;
DEFINE FIELD created_at ON relations TYPE datetime DEFAULT time::now();

-- 向量索引
DEFINE INDEX memory_embedding ON memories FIELDS content.embedding MTREE DIMENSION 1536;
DEFINE INDEX entity_embedding ON knowledge_graph FIELDS embedding MTREE DIMENSION 1536;
```

## Hook触发器

```yaml
hooks:
  after_session_end:
    script: "consolidate_memories.surql"

  scheduled:
    - name: "memory_cleanup"
      interval: "1h"
      script: "cleanup_memories.surql"
    - name: "knowledge_sync"
      interval: "30m"
      script: "sync_knowledge_graph.surql"
```

## 启动流程

```yaml
startup:
  1: "load_agents_config"
  2: "load_soul"
  3: "connect_surrealdb"
  4: "restore_recent_memories"
  5: "register_hooks"
  6: "start_cleanup_scheduler"
  7: "ready"
```
