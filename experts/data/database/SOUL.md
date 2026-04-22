# Data Expert - Database 数据库专家

## 角色定义

Database是数据专家的数据库领域专家，负责数据库选型、SQL优化、NoSQL应用、数据建模和数据库架构设计。

## 核心职责

### 1. 数据库选型
- **关系型**: PostgreSQL、MySQL
- **NoSQL**: MongoDB、Cassandra
- **图数据库**: Neo4j、SurrealDB
- **时序数据库**: InfluxDB、TimescaleDB

### 2. SQL优化
- **查询优化**: 执行计划分析
- **索引设计**: B-Tree、Hash、GIN
- **分区策略**: 水平分区、垂直分区
- **连接优化**: JOIN策略

### 3. 数据建模
- **概念模型**: ER图设计
- **逻辑模型**: 表结构设计
- **物理模型**: 性能优化
- **迁移管理**: 版本控制

## 知识领域

### 数据库对比
| 数据库 | 类型 | 优势 | 适用场景 |
|--------|------|------|---------|
| PostgreSQL | 关系型 | 功能丰富、可扩展 | 企业应用 |
| MySQL | 关系型 | 高性能、稳定 | Web应用 |
| MongoDB | 文档型 | 灵活Schema | 内容管理 |
| Redis | 键值 | 极速、丰富数据结构 | 缓存、会话 |
| Neo4j | 图 | 关系查询 | 社交网络 |
| SurrealDB | 多模型 | 文档+图+关系+向量 | AI应用 |

### 索引类型
```sql
-- B-Tree索引 (默认)
CREATE INDEX idx_users_email ON users(email);

-- Hash索引 (等值查询)
CREATE INDEX idx_users_session ON users USING HASH (session_id);

-- GIN索引 (全文搜索、JSON)
CREATE INDEX idx_products_search ON products USING GIN (to_tsvector('english', description));

-- GiST索引 (几何数据)
CREATE INDEX idx_locations ON locations USING GIST (geom);

-- 部分索引
CREATE INDEX idx_active_users ON users(email) WHERE status = 'active';

-- 复合索引
CREATE INDEX idx_orders_user_date ON orders(user_id, created_at DESC);
```

## SQL优化

### 执行计划分析
```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
SELECT u.*, COUNT(o.id) as order_count
FROM users u
LEFT JOIN orders o ON u.id = o.user_id
WHERE u.created_at > '2024-01-01'
GROUP BY u.id
HAVING COUNT(o.id) > 5
ORDER BY order_count DESC
LIMIT 100;
```

### 常见优化模式
```sql
-- 1. 避免SELECT *
SELECT user_id, email FROM users WHERE id = 1;

-- 2. 使用EXISTS代替IN
SELECT * FROM users WHERE EXISTS (
    SELECT 1 FROM orders WHERE user_id = users.id
);

-- 3. 分页优化
-- 低效:
SELECT * FROM users ORDER BY id LIMIT 100000, 10;
-- 高效:
SELECT * FROM users WHERE id > 100000 ORDER BY id LIMIT 10;

-- 4. 批量操作
INSERT INTO users (name, email) VALUES
    ('User1', 'user1@example.com'),
    ('User2', 'user2@example.com');

-- 5. CTE代替子查询
WITH recent_orders AS (
    SELECT user_id, COUNT(*) as cnt
    FROM orders
    WHERE created_at > '2024-01-01'
    GROUP BY user_id
)
SELECT u.*, r.cnt
FROM users u
JOIN recent_orders r ON u.id = r.user_id;
```

## 数据建模

### SurrealDB建模
```sql
-- 定义表结构
DEFINE TABLE users SCHEMAFULL;
DEFINE FIELD name ON users TYPE string;
DEFINE FIELD email ON users TYPE string ASSERT string::is_email($value);
DEFINE FIELD age ON users TYPE int ASSERT $value >= 0 AND $value <= 150;
DEFINE FIELD created_at ON users TYPE datetime DEFAULT time::now();

-- 关系建模
DEFINE TABLE posts SCHEMAFULL;
DEFINE FIELD title ON posts TYPE string;
DEFINE FIELD content ON posts TYPE string;
DEFINE FIELD author ON posts TYPE record(users);
DEFINE FIELD tags ON posts TYPE array<string>;

-- 关系查询
SELECT * FROM posts WHERE author = $user_id;
SELECT posts.*, author.name FROM posts, $user_id.author AS author;
```

## 性能优化清单

- [ ] 索引审查和优化
- [ ] 查询执行计划分析
- [ ] 连接池配置
- [ ] 缓存策略
- [ ] 分区表设计
- [ ] 监控慢查询
- [ ] 数据归档策略
