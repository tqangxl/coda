---
AIGC:
    ContentProducer: Minimax Agent AI
    ContentPropagator: Minimax Agent AI
    Label: AIGC
    ProduceID: "00000000000000000000000000000000"
    PropagateID: "00000000000000000000000000000000"
    ReservedCode1: 3046022100cb1ef3199aaadd850641de2640d8a0a9a3d3ba39b8a08f1821553ae61e90eb6b022100d9b96edfd64012ef01e4e7771bba94952eda4b5b7d9e9d24aadb14290e420353
    ReservedCode2: 3045022100dcffbbe6277421cb340e8d0f793bf7b954f4379dc15e396289a733293da16f6102205532b06a44cfa2d369fba615321561d077afed4dd53e524fdf8ca14b9d7f30e0
---

# Knowledge Graph - Storage 图谱存储

## 角色定义

Storage是Knowledge Graph的存储引擎，负责使用SurrealDB存储和管理图谱数据，提供高效的查询和检索能力。

## 核心职责

### 1. 数据建模
- **模式设计**: 设计图谱数据模型
- **表结构定义**: 定义SurrealDB表结构
- **索引优化**: 设计高效索引
- **分区策略**: 数据分区策略

### 2. 数据存储
- **实体存储**: 存储实体数据
- **关系存储**: 存储关系数据
- **属性存储**: 存储实体和关系属性
- **历史版本**: 版本历史管理

### 3. 查询优化
- **查询加速**: 优化查询性能
- **缓存策略**: 热点数据缓存
- **批量操作**: 批量读写优化
- **事务管理**: ACID事务支持

## SurrealDB存储架构

### 核心表结构

```sql
-- 实体主表
DEFINE TABLE entities SCHEMAFULL;
DEFINE FIELD id ON entities TYPE string;
DEFINE FIELD name ON entities TYPE string;
DEFINE FIELD type ON entities TYPE string;
DEFINE FIELD properties ON entities TYPE object;
DEFINE FIELD embedding ON entities TYPE array<float>;
DEFINE FIELD metadata ON entities TYPE object;
DEFINE FIELD status ON entities TYPE string DEFAULT 'active';
DEFINE FIELD created_at ON entities TYPE datetime;
DEFINE FIELD updated_at ON entities TYPE datetime;
DEFINE FIELD version ON entities TYPE int DEFAULT 1;

-- 关系主表
DEFINE TABLE relations SCHEMAFULL;
DEFINE FIELD id ON entities TYPE string;
DEFINE FIELD type ON entities TYPE string;
DEFINE FIELD from_entity ON entities TYPE string;
DEFINE FIELD to_entity ON entities TYPE string;
DEFINE FIELD properties ON entities TYPE object;
DEFINE FIELD weight ON entities TYPE float DEFAULT 1.0;
DEFINE FIELD confidence ON entities TYPE float;
DEFINE FIELD metadata ON entities TYPE object;
DEFINE FIELD status ON entities TYPE string DEFAULT 'active';
DEFINE FIELD created_at ON entities TYPE datetime;
DEFINE FIELD updated_at ON entities TYPE datetime;
```

### 索引设计

```sql
-- 实体索引
DEFINE INDEX idx_entity_type ON entities FIELDS type;
DEFINE INDEX idx_entity_name ON entities FIELDS name;
DEFINE INDEX idx_entity_name_type ON entities FIELDS name, type;
DEFINE INDEX idx_entity_embedding ON entities FIELDS embedding MTREE DIMENSION 1536;

-- 关系索引
DEFINE INDEX idx_relation_type ON relations FIELDS type;
DEFINE INDEX idx_relation_from ON relations FIELDS from_entity;
DEFINE INDEX idx_relation_to ON relations FIELDS to_entity;
DEFINE INDEX idx_relation_pair ON relations FIELDS from_entity, to_entity, type;
DEFINE INDEX idx_relation_weight ON relations FIELDS weight;

-- 复合索引
DEFINE INDEX idx_entity_relation ON entities FIELDS type, status;
DEFINE INDEX idx_relation_meta ON relations FIELDS type, status;
```

### 图查询优化

```sql
-- 1跳邻居查询
DEFINE FUNCTION fn::get_neighbors($entity_id: string) {
    SELECT * FROM relations
    WHERE from_entity = $entity_id OR to_entity = $entity_id
    RETURN {entity: (from_entity IF from_entity != $entity_id ELSE to_entity), relation: id, type: type};
};

-- 2跳路径查询
DEFINE FUNCTION fn::get_2hop_path($start: string, $end: string) {
    SELECT
        r1.from_entity as step1,
        r1.to_entity as step2,
        r2.to_entity as step3
    FROM relations r1, relations r2
    WHERE r1.from_entity = $start
    AND r2.from_entity = r1.to_entity
    AND r2.to_entity = $end
    RETURN {path: [step1, step2, step3]};
};
```

## 数据存储策略

### 分层存储
```yaml
storage_tiers:
  hot:
    data: "高频访问实体和关系"
    storage: "内存/Surrealkv"
    ttl: "7天"

  warm:
    data: "中频访问数据"
    storage: "RocksDB"
    ttl: "30天"

  cold:
    data: "低频访问历史数据"
    storage: "TiKV/对象存储"
    ttl: "永久"
```

### 向量存储
```sql
-- 向量索引配置
DEFINE INDEX entity_vector ON entities
    FIELDS embedding
    MTREE
    DIMENSION 1536
    TYPE f32
    DISTANCE cosine;

-- 相似实体查询
SELECT id, name,
    vector::distance::cosine(embedding, $query_embedding) as similarity
FROM entities
WHERE type = $type
ORDER BY similarity ASC
LIMIT 10;
```

## 事务管理

### 原子操作
```sql
-- 创建实体和关系（原子操作）
BEGIN TRANSACTION;

CREATE entities CONTENT {
    id: "entity_new",
    name: "New Entity",
    type: "concept",
    properties: {},
    created_at: time::now()
};

CREATE relations CONTENT {
    id: "rel_new",
    type: "related_to",
    from_entity: "entity_new",
    to_entity: "entity_existing",
    properties: {},
    created_at: time::now()
};

COMMIT;
```

### 批量操作
```python
async def batch_insert_entities(self, entities):
    """批量插入实体"""
    batch_size = 1000
    results = []

    for i in range(0, len(entities), batch_size):
        batch = entities[i:i+batch_size]

        # 构造批量INSERT
        values = [
            f"{{id: '{e.id}', name: '{e.name}', type: '{e.type}', properties: {e.properties}}}"
            for e in batch
        ]

        query = f"INSERT INTO entities [ {','.join(values)} ]"
        result = await db.query(query)
        results.extend(result)

    return results
```

## 版本控制

### 实体版本
```sql
-- 版本历史表
DEFINE TABLE entity_versions SCHEMAFULL;
DEFINE FIELD id ON entity_versions TYPE string;
DEFINE FIELD entity_id ON entity_versions TYPE string;
DEFINE FIELD version ON entity_versions TYPE int;
DEFINE FIELD data ON entity_versions TYPE object;
DEFINE FIELD changed_by ON entity_versions TYPE string;
DEFINE FIELD changed_at ON entity_versions TYPE datetime;
DEFINE FIELD change_type ON entity_versions TYPE string;
DEFINE FIELD change_reason ON entity_versions TYPE option<string>;

-- 创建版本记录
DEFINE FUNCTION fn::create_entity_version($entity_id: string, $change_type: string) {
    LET $entity = SELECT * FROM entities WHERE id = $entity_id FIRST;
    LET $max_version = SELECT math::max(version) FROM entity_versions WHERE entity_id = $entity_id GROUP ALL;
    CREATE entity_versions CONTENT {
        id: uuid(),
        entity_id: $entity_id,
        version: ($max_version.version + 1),
        data: $entity,
        change_type: $change_type,
        changed_at: time::now()
    };
};
```

### 版本查询
```sql
-- 查询实体历史
SELECT * FROM entity_versions
WHERE entity_id = $entity_id
ORDER BY version DESC;

-- 回滚到指定版本
DEFINE FUNCTION fn::rollback_entity($entity_id: string, $version: int) {
    LET $version_data = SELECT data FROM entity_versions
        WHERE entity_id = $entity_id AND version = $version FIRST;
    UPDATE entities SET * FROM $version_data.data WHERE id = $entity_id;
};
```

## 缓存策略

### 热点数据缓存
```python
CACHE_CONFIG = {
    "entity": {
        "hot_threshold": 100,  # 访问次数
        "ttl": 3600,  # 1小时
        "max_size": 10000
    },
    "relation": {
        "hot_threshold": 50,
        "ttl": 1800,  # 30分钟
        "max_size": 50000
    }
}

async def get_entity(self, entity_id):
    """获取实体，支持缓存"""
    # 检查缓存
    cached = await cache.get(f"entity:{entity_id}")
    if cached:
        return cached

    # 从数据库获取
    entity = await db.select("entities", entity_id)

    # 更新缓存
    if entity:
        await cache.set(
            f"entity:{entity_id}",
            entity,
            ttl=CACHE_CONFIG["entity"]["ttl"]
        )

    return entity
```

## 数据迁移

### Schema迁移
```python
async def migrate_schema(self, from_version, to_version):
    """执行Schema迁移"""
    migrations = {
        "1.0->1.1": self.migrate_add_embedding,
        "1.1->1.2": self.migrate_add_metadata
    }

    for version, migration in migrations.items():
        if from_version < version:
            await migration()
            from_version = version

async def migrate_add_embedding(self):
    """添加embedding字段"""
    await db.query("""
        DEFINE FIELD embedding ON entities TYPE option<array<float>>;
    """)
```

## 备份恢复

### 备份策略
```yaml
backup:
  schedule:
    full: "daily at 02:00"
    incremental: "every 6 hours"

  retention:
    daily: 7
    weekly: 4
    monthly: 12

  storage:
    local: "/backup/kg"
    remote: "s3://backup-bucket/kg"
```

### 恢复操作
```python
async def restore_from_backup(self, backup_path):
    """从备份恢复"""
    # 1. 停止写入
    await self.set_write_mode("readonly")

    # 2. 清空当前数据
    await db.query("DELETE FROM entities")
    await db.query("DELETE FROM relations")

    # 3. 恢复数据
    await db.import_from(backup_path)

    # 4. 恢复写入
    await self.set_write_mode("normal")
```

## 监控指标

```sql
-- 存储统计
SELECT
    count() as total_entities,
    count() FILTER WHERE status = 'active' as active_entities,
    count() as total_relations,
    count() FILTER WHERE status = 'active' as active_relations,
    math::avg(vector::len(embedding)) as avg_embedding_size
FROM entities, relations;
```
