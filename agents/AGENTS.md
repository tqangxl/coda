# AI Agent团队 - Agent配置文件索引

## 角色启动顺序

Agent加载时应按以下顺序读取配置文件：

```
1. AGENTS.md (本文档) - 团队配置和Agent清单
2. SOUL.md - Agent灵魂定义
3. 自身记忆 - 从SurrealDB读取 (namespace: ai_agents_v2)
4. 任务队列 - 从SurrealDB读取 (table: agent_tasks)
```

## 团队配置

```yaml
team:
  name: "AI Agent Team V2.0"
  namespace: "ai_agents_v2"  # 隔离命名空间
  database: "agent_system_v2"

agents:
  - id: "commander"
    name: "Commander"
    priority: 1  # 优先级最高
    auto_start: true

  - id: "generator"
    name: "Generator"
    priority: 2
    auto_start: true

  - id: "verifier"
    name: "Verifier"
    priority: 3
    auto_start: true

  - id: "coder"
    name: "Coder"
    priority: 4
    auto_start: true

  - id: "memory-keeper"
    name: "MemoryKeeper"
    priority: 5
    auto_start: true

  - id: "profile-manager"
    name: "ProfileManager"
    priority: 6
    auto_start: true

  - id: "domain-expert"
    name: "DomainExpert"
    priority: 7
    auto_start: false  # 按需加载

  - id: "study-manager"
    name: "StudyManager"
    priority: 8
    auto_start: true

  - id: "schedule-manager"
    name: "ScheduleManager"
    priority: 9
    auto_start: true

  - id: "banking-expert"
    name: "BankingAuditExpert"
    priority: 10
    auto_start: false  # 专家角色，按需加载
```

## cx Token优化配置

每个Agent在向LLM发送请求前必须执行cx优化：

```yaml
cx_optimization:
  enabled: true
  commands:
    - name: "overview"
      token_limit: 200
      description: "文件结构概览"
    - name: "definition"
      token_limit: 200
      description: "函数/类定义"
    - name: "symbols"
      token_limit: 70
      description: "符号列表"
    - name: "references"
      token_limit: 20
      description: "引用追踪"

## SYSTEM SAFEGUARDS (系统规约)

为了确保系统的稳定性和一致性，所有 Agent 的开发与运维操作必须无限制地遵守以下规约：

### 1. 数据库强化规约 (SurrealDB 3.x)
- **类型安全性**: 在 `SCHEMAFULL` 表定义中，所有时间戳字段必须声明为 `option<datetime>`。
- **通信协议**: 通过 Python SDK 写入时，必须传递原生的 Python `datetime` 对象，严禁传递 ISO 字符串，以规避 SDK 层的类型强制转换失败。
- **结果解析**: 必须支持多格式解析模式（Wrapped Result 或 Flat List），以兼容 SurrealDB 不同版本及多查询返回。

### 2. 进程与资源规约 (Process & Network)
- **进程树清理**: 在 Windows 环境下，任何后台服务或端口占用者的释放必须调用 `taskkill /F /PID <pid> /T`。禁止使用常规的 `Stop-Process` 或不带 `/T` 的杀除，以确保子进程树被完整清理。
- **网络确定性**: 所有 `.env` 配置、API 回调及数据库连接入口禁止使用 `localhost`，必须强制指定为 `127.0.0.1`，以规避系统双栈解析带来的延迟与握手错误。
- **绝对路径锚定**: 所有的部署与启动脚本在入口层必须首先定位 `$PROJECT_ROOT` 的物理绝对路径，拒绝一切基于相对路径的执行假设。

---

  auto_invoke:
    before_llm_call: true
    context_window_check: true
    max_token_budget: 8000
```

## 记忆配置

```yaml
memory:
  namespace: "ai_agents_v2"
  tables:
    agent_memories: "agent_memories_{agent_id}"
    shared_knowledge: "shared_knowledge"
    session_history: "session_history"

  retention:
    short_term: "24h"
    medium_term: "7d"
    long_term: "30d"
```

## 任务队列配置

```yaml
task_queue:
  namespace: "ai_agents_v2"
  table: "agent_tasks"

  priority_levels:
    critical: 100
    high: 75
    medium: 50
    low: 25

  status:
    - pending
    - in_progress
    - waiting_input
    - completed
    - failed
```

## SurrealDB连接配置

```yaml
surrealdb:
  namespace: "ai_agents_v2"  # 独立命名空间，与其他应用隔离
  database: "agent_system_v2"

  connection:
    protocol: "ws"  # or "http"
    host: "127.0.0.1"
    port: 11001
    auth:
      user: "root"
      pass: "${SURREALDB_PASS}"  # 从环境变量读取

  paths:
    unix: "/var/run/surrealdb/socket"  # Linux
    windows: "\\\\.\\pipe\\surrealdb"  # Windows

  isolation:
    enabled: true
    prefix: "v2_"  # 所有表名前缀，避免与其他应用冲突
```

## Hook运行环境

```yaml
hook_runtime:
  enabled: true
  namespace: "ai_agents_v2"

  triggers:
    - after_task_complete
    - after_session_end
    - on_error
    - scheduled_interval

  storage:
    table: "hook_events"
    history_table: "hook_history"

  scheduler:
    enabled: true
    default_interval: "30m"  # 默认30分钟检查一次
    tables:
      schedules: "hook_schedules"
      executions: "hook_executions"
```

## 微信集成配置

```yaml
wechat:
  enabled: false
  webhook_url: "${WECHAT_WEBHOOK_URL}"

  notifications:
    - task_completed
    - error_alert
    - daily_summary
```

## 启动参数

```yaml
startup:
  load_order:
    - "AGENTS.md"
    - "surreal:init"
    - "agents:load"
    - "hooks:register"
    - "wechat:connect"

  health_check:
    enabled: true
    interval: "60s"
    endpoint: "/health"
```
