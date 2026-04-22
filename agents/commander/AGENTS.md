# Commander Agent - Agent配置

## 基本信息

```yaml
agent:
  id: "commander"
  name: "Commander"
  type: "orchestrator"
  version: "2.0.0"
  namespace: "ai_agents_v2"
```

## 职责

- 任务调度与团队协调
- A2A协议消息路由
- Kanban看板管理
- 质量门禁检查

## cx优化配置

```yaml
cx_config:
  enabled: true

  before_llm_call:
    - command: "symbols"
      reason: "了解可用Agent能力"
    - command: "overview"
      reason: "了解项目结构"
```

## 记忆配置

```yaml
memory:
  type: "shared"
  table: "commander_memory"

  stores:
    - type: "task_context"
      ttl: "24h"
    - type: "team_state"
      ttl: "1h"
    - type: "coordination_log"
      ttl: "7d"
```

## 任务队列

```yaml
tasks:
  input_queue: "commander_inbox"
  output_queue: "commander_outbox"

  priority_handling:
    critical: "immediate"
    high: "within_5m"
    medium: "within_30m"
    low: "batch"
```

## SurrealDB表

```sql
-- Commander专用表
DEFINE TABLE commander_memory SCHEMAFULL;
DEFINE FIELD agent_id ON commander_memory TYPE string DEFAULT 'commander';
DEFINE FIELD memory_type ON commander_memory TYPE string;
DEFINE FIELD content ON commander_memory TYPE object;
DEFINE FIELD context ON commander_memory TYPE object;
DEFINE FIELD created_at ON commander_memory TYPE datetime DEFAULT time::now();

DEFINE TABLE commander_tasks SCHEMAFULL;
DEFINE FIELD agent_id ON commander_tasks TYPE string DEFAULT 'commander';
DEFINE FIELD task_id ON commander_tasks TYPE string;
DEFINE FIELD status ON commander_tasks TYPE string;
DEFINE FIELD priority ON commander_tasks TYPE int;
DEFINE FIELD assigned_to ON commander_tasks TYPE option<string>;
DEFINE FIELD created_at ON commander_tasks TYPE datetime DEFAULT time::now();
```

## Hook触发器

```yaml
hooks:
  after_task_complete:
    script: "on_task_complete.surql"

  after_session_end:
    script: "generate_session_summary.surql"

  on_error:
    script: "handle_commander_error.surql"
```

## 启动流程

```yaml
startup:
  1: "load_team_config"      # 加载AGENTS.md
  2: "connect_surrealdb"     # 连接SurrealDB
  3: "restore_memory"         # 恢复记忆
  4: "register_hooks"        # 注册Hook
  5: "start_kanban"          # 启动看板监控
  6: "heartbeat"             # 开始心跳
```
