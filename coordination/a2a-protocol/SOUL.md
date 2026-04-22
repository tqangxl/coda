

# A2A Protocol - Agent间通信协议

## 协议定义

A2A(Agent-to-Agent)协议是Agent间通信的标准协议，定义了消息格式、交互模式和协作规范，使多个Agent能够高效协作。

## 核心职责

### 1. 消息定义
- **消息格式**: 统一的消息结构
- **消息类型**: 定义各种消息类型
- **消息路由**: 消息的发送和路由
- **消息确认**: 消息的确认机制

### 2. 交互模式
- **请求-响应**: 同步请求响应
- **发布-订阅**: 事件通知模式
- **RPC调用**: 远程过程调用
- **流式响应**: 流式数据交互

### 3. 协议实现
- **连接管理**: Agent连接管理
- **错误处理**: 通信错误处理
- **重试机制**: 消息重试策略
- **安全传输**: 消息加密和认证

## SurrealDB协议模型

```sql
-- Agent注册
DEFINE TABLE agent_registry SCHEMAFULL;
DEFINE FIELD id ON agent_registry TYPE string;
DEFINE FIELD name ON agent_registry TYPE string;
DEFINE FIELD type ON agent_registry TYPE string;
DEFINE FIELD capabilities ON agent_registry TYPE array;
DEFINE FIELD endpoint ON agent_registry TYPE string;
DEFINE FIELD status ON agent_registry TYPE string DEFAULT 'offline';
DEFINE FIELD last_seen ON agent_registry TYPE datetime;
DEFINE FIELD metadata ON agent_registry TYPE object;
DEFINE FIELD created_at ON agent_registry TYPE datetime;

-- 消息记录
DEFINE TABLE a2a_messages SCHEMAFULL;
DEFINE FIELD id ON a2a_messages TYPE string;
DEFINE FIELD message_type ON a2a_messages TYPE string;
DEFINE FIELD from_agent ON a2a_messages TYPE string;
DEFINE FIELD to_agent ON a2a_messages TYPE string;
DEFINE FIELD payload ON a2a_messages TYPE object;
DEFINE FIELD correlation_id ON a2a_messages TYPE string;
DEFINE FIELD reply_to ON a2a_messages TYPE option<string>;
DEFINE FIELD status ON a2a_messages TYPE string;
DEFINE FIELD created_at ON a2a_messages TYPE datetime;
DEFINE FIELD delivered_at ON a2a_messages TYPE option<datetime>;

-- 会话管理
DEFINE TABLE a2a_sessions SCHEMAFULL;
DEFINE FIELD id ON a2a_sessions TYPE string;
DEFINE FIELD participants ON a2a_sessions TYPE array;
DEFINE FIELD context ON a2a_sessions TYPE object;
DEFINE FIELD status ON a2a_sessions TYPE string;
DEFINE FIELD created_at ON a2a_sessions TYPE datetime;
DEFINE FIELD updated_at ON a2a_sessions TYPE datetime;

-- 索引
DEFINE INDEX idx_message_from ON a2a_messages FIELDS from_agent, created_at DESC;
DEFINE INDEX idx_message_to ON a2a_messages FIELDS to_agent, status, created_at DESC;
DEFINE INDEX idx_session ON a2a_sessions FIELDS participants, status;
```

## 消息格式

### 基础消息结构
```json
{
  "id": "msg_xxx",
  "type": "task_request",
  "from": "commander",
  "to": "generator",
  "payload": {
    "task_id": "task_001",
    "intent": "generate_solution",
    "context": {...},
    "priority": "high"
  },
  "metadata": {
    "correlation_id": "corr_001",
    "reply_to": "msg_yyy",
    "timestamp": "2026-03-31T00:15:00Z",
    "ttl": 300
  },
  "security": {
    "auth_token": "xxx",
    "signature": "xxx"
  }
}
```

### 消息类型

| 类型 | 说明 | 方向 | 模式 |
|------|------|------|------|
| task_request | 请求执行任务 | → | Request-Response |
| task_response | 返回任务结果 | ← | Request-Response |
| status_update | 状态更新通知 | → | Publish-Subscribe |
| help_request | 请求协助 | → | RPC |
| help_response | 返回协助结果 | ← | RPC |
| cancel_request | 取消任务 | → | Request-Response |
| event_notification | 事件通知 | → | Publish-Subscribe |
| heartbeat | 心跳检测 | ↔ | Stream |

## 消息类型详解

### 1. Task Request
```json
{
  "type": "task_request",
  "payload": {
    "task_id": "task_001",
    "intent": "generate_code",
    "parameters": {
      "language": "python",
      "requirements": "实现用户认证API"
    },
    "constraints": {
      "max_time": 60,
      "max_tokens": 5000
    },
    "priority": "high"
  }
}
```

### 2. Task Response
```json
{
  "type": "task_response",
  "payload": {
    "task_id": "task_001",
    "status": "completed",
    "result": {
      "code": "def authenticate(): ...",
      "files": ["auth.py", "test_auth.py"]
    },
    "metrics": {
      "duration_ms": 2500,
      "tokens_used": 3500
    }
  },
  "reply_to": "msg_001"
}
```

### 3. Status Update
```json
{
  "type": "status_update",
  "payload": {
    "task_id": "task_001",
    "status": "in_progress",
    "progress": 0.65,
    "message": "正在生成代码..."
  }
}
```

### 4. Error Response
```json
{
  "type": "error_response",
  "payload": {
    "error_code": "VALIDATION_ERROR",
    "message": "参数验证失败",
    "details": {
      "field": "language",
      "reason": "不支持该编程语言"
    }
  },
  "reply_to": "msg_001"
}
```

## 交互模式

### 1. Request-Response
```python
async def request_response(self, to_agent, payload, timeout=60):
    """请求-响应模式"""
    # 1. 生成消息ID
    msg_id = f"msg_{uuid()}"
    correlation_id = f"corr_{uuid()}"

    # 2. 发送请求
    await self.send({
        "id": msg_id,
        "type": "task_request",
        "from": self.agent_id,
        "to": to_agent,
        "payload": payload,
        "metadata": {
            "correlation_id": correlation_id,
            "reply_to": msg_id
        }
    })

    # 3. 等待响应
    response = await self.wait_for_response(
        correlation_id,
        timeout=timeout
    )

    return response
```

### 2. Publish-Subscribe
```python
class EventBus:
    async def publish(self, event_type, payload):
        """发布事件"""
        message = {
            "type": "event_notification",
            "from": self.agent_id,
            "payload": {
                "event_type": event_type,
                "data": payload
            }
        }

        # 查找订阅者
        subscribers = await self.find_subscribers(event_type)

        # 发送消息给所有订阅者
        for subscriber in subscribers:
            await self.send_to(subscriber, message)

    async def subscribe(self, event_type, callback):
        """订阅事件"""
        await db.create("subscriptions", {
            "agent_id": self.agent_id,
            "event_type": event_type,
            "callback": callback,
            "created_at": datetime.now()
        })
```

### 3. RPC调用
```python
async def rpc_call(self, agent, method, params):
    """RPC调用"""
    return await self.request_response(agent, {
        "rpc_method": method,
        "params": params
    })
```

## 协议实现

### 连接管理
```python
class AgentConnection:
    def __init__(self, agent_id):
        self.agent_id = agent_id
        self.connections = {}
        self.message_queue = asyncio.Queue()

    async def connect(self, target_agent):
        """建立连接"""
        registry = await db.get("agent_registry", target_agent)

        if not registry or registry.status != "online":
            raise ConnectionError(f"Agent {target_agent} is not available")

        self.connections[target_agent] = {
            "endpoint": registry.endpoint,
            "established_at": datetime.now()
        }

    async def disconnect(self, target_agent):
        """断开连接"""
        if target_agent in self.connections:
            del self.connections[target_agent]

    async def send(self, message):
        """发送消息"""
        # 添加发送时间戳
        message["metadata"]["sent_at"] = datetime.now().isoformat()

        # 记录消息
        await db.create("a2a_messages", message)

        # 发送到目标
        target = self.connections.get(message["to"])
        if target:
            await self.transport.send(target["endpoint"], message)
```

### 消息确认
```python
async def acknowledge_message(self, message_id):
    """确认消息"""
    await db.update("a2a_messages", {
        "id": message_id,
        "status": "delivered",
        "delivered_at": datetime.now()
    })
```

### 重试机制
```python
RETRY_CONFIG = {
    "max_retries": 3,
    "backoff": "exponential",
    "initial_delay": 1,
    "max_delay": 30,
    "retryable_errors": [
        "CONNECTION_TIMEOUT",
        "TRANSPORT_ERROR",
        "AGENT_BUSY"
    ]
}

async def send_with_retry(self, message, max_retries=3):
    """带重试的消息发送"""
    for attempt in range(max_retries):
        try:
            await self.send(message)
            return {"status": "sent"}
        except RetryableError as e:
            if attempt == max_retries - 1:
                raise
            delay = self.calculate_backoff(attempt)
            await asyncio.sleep(delay)
```

## 错误处理

### 错误代码
```yaml
error_codes:
  VALIDATION_ERROR:
    http_code: 400
    retry: false
    description: "参数验证失败"

  UNAUTHORIZED:
    http_code: 401
    retry: false
    description: "认证失败"

  AGENT_NOT_FOUND:
    http_code: 404
    retry: false
    description: "Agent不存在"

  AGENT_BUSY:
    http_code: 503
    retry: true
    description: "Agent忙，请重试"

  TIMEOUT:
    http_code: 504
    retry: true
    description: "请求超时"
```

## 安全机制

### 认证
```python
SECURITY_CONFIG = {
    "authentication": {
        "method": "token",
        "token_expiry": 3600
    },
    "encryption": {
        "algorithm": "AES-256-GCM",
        "key_rotation": 86400
    }
}
```

### 消息签名
```python
async def sign_message(self, message):
    """消息签名"""
    content = json.dumps(message["payload"], sort_keys=True)
    signature = hmac.new(
        self.secret_key,
        content.encode(),
        hashlib.sha256
    ).hexdigest()

    message["security"]["signature"] = signature
    return message
```

## 监控指标

```sql
-- 消息统计
SELECT
    message_type,
    count(*) as total,
    count(*) FILTER WHERE status = 'delivered' as delivered,
    count(*) FILTER WHERE status = 'failed' as failed,
    avg(delivered_at - created_at) as avg_latency
FROM a2a_messages
WHERE created_at > time::now() - 1h
GROUP BY message_type;
```
