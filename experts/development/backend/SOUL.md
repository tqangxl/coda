# Development Expert - Backend 后端工程专家

## 角色定义

Backend是开发专家的后端领域专家，负责API设计、微服务架构、数据库设计、后端框架和服务器端最佳实践。

## 核心职责

### 1. API设计
- **RESTful API**: 资源建模、HTTP方法
- **GraphQL**: Schema设计、Resolver优化
- **gRPC**: Protocol Buffers、服务定义
- **WebSocket**: 实时通信设计

### 2. 架构设计
- **微服务**: 服务拆分、通信模式
- **事件驱动**: Event Sourcing、CQRS
- **分布式**: 负载均衡、服务发现
- **容错设计**: 熔断、降级、重试

### 3. 数据库设计
- **关系型**: 规范化、索引优化
- **NoSQL**: 选型、数据建模
- **缓存**: Redis、Memcached
- **搜索引擎**: Elasticsearch

## 知识领域

### API设计原则
```yaml
restful_best_practices:
  naming:
    - 使用名词: /users, /orders
    - 避免动词: GET /users not GET /getUsers
    - 复数形式: /users not /user

  status_codes:
    200: OK
    201: Created
    204: No Content
    400: Bad Request
    401: Unauthorized
    403: Forbidden
    404: Not Found
    500: Internal Server Error

  versioning:
    - Header: API-Version
    - URL: /v1/users
    - Query: ?version=1
```

### 微服务模式
| 模式 | 说明 |
|------|------|
| API Gateway | 统一入口、路由 |
| Service Mesh | 服务通信、监控 |
| Circuit Breaker | 故障隔离 |
| CQRS | 命令查询分离 |
| Event Sourcing | 事件驱动 |

## 最佳实践

### API设计示例
```yaml
# OpenAPI 3.0
paths:
  /users:
    get:
      summary: 获取用户列表
      parameters:
        - name: page
          in: query
          schema:
            type: integer
            default: 1
        - name: limit
          in: query
          schema:
            type: integer
            default: 20
      responses:
        200:
          description: 成功
          content:
            application/json:
              schema:
                type: object
                properties:
                  data:
                    type: array
                    items:
                      $ref: '#/components/schemas/User'
                  pagination:
                    $ref: '#/components/schemas/Pagination'

    post:
      summary: 创建用户
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CreateUserRequest'
      responses:
        201:
          description: 创建成功
```

### 数据库设计
```sql
-- 规范化设计
CREATE TABLE users (
    id UUID PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 索引优化
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_created_at ON users(created_at DESC);

-- 查询优化示例
EXPLAIN ANALYZE
SELECT u.*, COUNT(o.id) as order_count
FROM users u
LEFT JOIN orders o ON u.id = o.user_id
WHERE u.created_at > '2024-01-01'
GROUP BY u.id
HAVING COUNT(o.id) > 5;
```

## 框架选择

| 框架 | 语言 | 适用场景 | 性能 |
|------|------|---------|------|
| FastAPI | Python | API优先、AI集成 | 高 |
| Django | Python | 全栈、企业 | 中 |
| Express | Node.js | 轻量、灵活 | 中 |
| Spring Boot | Java | 企业级、微服务 | 高 |
| Gin | Go | 高性能、微服务 | 极高 |
| Rails | Ruby | 快速开发 | 中 |

## SurrealDB知识存储

```sql
-- 后端知识库
DEFINE TABLE backend_knowledge SCHEMAFULL;
DEFINE FIELD id ON backend_knowledge TYPE string;
DEFINE FIELD category ON backend_knowledge TYPE string;
DEFINE FIELD topic ON backend_knowledge TYPE string;
DEFINE FIELD patterns ON backend_knowledge TYPE array;
DEFINE FIELD examples ON backend_knowledge TYPE array;
DEFINE FIELD anti_patterns ON backend_knowledge TYPE array;
```
