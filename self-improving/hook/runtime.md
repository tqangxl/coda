# Hook自动触发运行环境

## 概述

Hook运行环境是Self-Improving Agent的核心组件，负责在特定事件发生时自动触发学习流程，实现系统的持续改进。

## 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                   Hook Runtime Engine                           │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │  Event Bus │  │ Rule Engine │  │ Scheduler   │         │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
│         │                │                │                 │
│  ┌──────▼──────────────────▼──────────────────▼──────┐    │
│  │              Action Executor                       │    │
│  └──────┬──────────────────┬──────────────────┬─────┘    │
│         │                  │                  │             │
│  ┌──────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐       │
│  │  Learning   │  │  Notifier   │  │  Database   │       │
│  └─────────────┘  └─────────────┘  └─────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

## 事件类型

### 系统事件
```yaml
system_events:
  task_started:
    description: "任务开始执行"
    data:
      - task_id
      - task_type
      - agent_id
      - timestamp

  task_completed:
    description: "任务完成"
    data:
      - task_id
      - duration
      - success
      - output
      - tokens_used

  task_failed:
    description: "任务失败"
    data:
      - task_id
      - error_type
      - error_message
      - retry_count
```

### 用户事件
```yaml
user_events:
  feedback_received:
    description: "收到用户反馈"
    data:
      - task_id
      - rating
      - comment
      - sentiment

  preference_changed:
    description: "偏好变化"
    data:
      - preference_type
      - old_value
      - new_value
```

### 定时事件
```yaml
scheduled_events:
  hourly:
    description: "每小时触发"
    use_cases:
      - 统计汇总
      - 状态检查

  daily:
    description: "每天触发"
    use_cases:
      - 生成日报
      - 清理过期数据

  weekly:
    description: "每周触发"
    use_cases:
      - 生成周报
      - 技能升级检查
```

## SurrealDB配置

```sql
-- Hook配置表
DEFINE TABLE hook_configs SCHEMAFULL;
DEFINE FIELD id ON hook_configs TYPE string;
DEFINE FIELD name ON hook_configs TYPE string;
DEFINE FIELD event_type ON hook_configs TYPE string;
DEFINE FIELD conditions ON hook_configs TYPE array;
DEFINE FIELD actions ON hook_configs TYPE array;
DEFINE FIELD priority ON hook_configs TYPE int DEFAULT 0;
DEFINE FIELD enabled ON hook_configs TYPE bool DEFAULT true;
DEFINE FIELD created_at ON hook_configs TYPE datetime DEFAULT time::now();

-- Hook执行记录
DEFINE TABLE hook_executions SCHEMAFULL;
DEFINE FIELD id ON hook_executions TYPE string;
DEFINE FIELD hook_id ON hook_executions TYPE string;
DEFINE FIELD event_type ON hook_executions TYPE string;
DEFINE FIELD trigger_data ON hook_executions TYPE object;
DEFINE FIELD conditions_met ON hook_executions TYPE array;
DEFINE FIELD actions_executed ON hook_executions TYPE array;
DEFINE FIELD result ON hook_executions TYPE string;
DEFINE FIELD duration_ms ON hook_executions TYPE int;
DEFINE FIELD executed_at ON hook_executions TYPE datetime DEFAULT time::now();

-- 定时任务表
DEFINE TABLE hook_schedules SCHEMAFULL;
DEFINE FIELD id ON hook_schedules TYPE string;
DEFINE FIELD name ON hook_schedules TYPE string;
DEFINE FIELD cron_expression ON hook_schedules TYPE string;
DEFINE FIELD script ON hook_schedules TYPE string;
DEFINE FIELD enabled ON hook_schedules TYPE bool DEFAULT true;
DEFINE FIELD last_run ON hook_schedules TYPE option<datetime>;
DEFINE FIELD next_run ON hook_schedules TYPE option<datetime>;
DEFINE FIELD created_at ON hook_schedules TYPE datetime DEFAULT time::now();

-- 事件记录
DEFINE TABLE hook_events SCHEMAFULL;
DEFINE FIELD id ON hook_events TYPE string;
DEFINE FIELD event_type ON hook_events TYPE string;
DEFINE FIELD source ON hook_events TYPE string;
DEFINE FIELD data ON hook_events TYPE object;
DEFINE FIELD timestamp ON hook_events TYPE datetime DEFAULT time::now();

-- 索引
DEFINE INDEX idx_hook_config_event ON hook_configs FIELDS event_type, enabled;
DEFINE INDEX idx_hook_execution_time ON hook_executions FIELDS executed_at DESC;
DEFINE INDEX idx_hook_schedule_cron ON hook_schedules FIELDS cron_expression, enabled;
```

## 内置Hook配置

### 1. 任务完成Hook
```yaml
hook:
  name: "on_task_complete"
  event_type: "task_completed"
  conditions:
    - field: "success"
      operator: "eq"
      value: true
  actions:
    - type: "learning"
      subtype: "extract_success_pattern"
      params:
        min_confidence: 0.8
```

### 2. 任务失败Hook
```yaml
hook:
  name: "on_task_failed"
  event_type: "task_failed"
  conditions:
    - field: "retry_count"
      operator: "gte"
      value: 3
  actions:
    - type: "learning"
      subtype: "root_cause_analysis"
    - type: "notification"
      channel: "commander"
      message: "任务失败，需要关注"
```

### 3. 定期清理Hook
```yaml
hook:
  name: "memory_cleanup"
  event_type: "scheduled"
  cron: "0 * * * *"  # 每小时
  actions:
    - type: "database"
      subtype: "cleanup_old_memories"
      params:
        retention_days: 7
```

### 4. 定期技能升级Hook
```yaml
hook:
  name: "skill_upgrade_check"
  event_type: "scheduled"
  cron: "0 2 * * 0"  # 每周日凌晨2点
  actions:
    - type: "learning"
      subtype: "analyze_skill_effectiveness"
    - type: "learning"
      subtype: "suggest_skill_improvements"
```

### 5. 会话结束Hook
```yaml
hook:
  name: "after_session_end"
  event_type: "session_ended"
  actions:
    - type: "learning"
      subtype: "consolidate_session"
    - type: "database"
      subtype: "save_session_summary"
    - type: "notification"
      subtype: "send_summary"
      params:
        channels: ["wechat"]
```

## 执行器实现

### Python实现
```python
import asyncio
from datetime import datetime
from surrealdb import Surreal

class HookRuntime:
    def __init__(self, db: Surreal, namespace: str = "ai_agents_v2"):
        self.db = db
        self.namespace = namespace

    async def start(self):
        """启动Hook运行时"""
        # 1. 连接数据库
        await self.db.connect()
        await self.db.signin({
            "user": "root",
            "pass": os.getenv("SURREALDB_PASS")
        })
        await self.db.use({
            "namespace": self.namespace,
            "database": "agent_system"
        })

        # 2. 启动事件监听
        asyncio.create_task(self.listen_events())

        # 3. 启动定时调度器
        asyncio.create_task(self.run_scheduler())

        # 4. 启动心跳
        asyncio.create_task(self.heartbeat())

    async def listen_events(self):
        """监听事件"""
        # 使用SurrealDB的实时查询
        async for event in self.db.listen("hook_events"):
            await self.process_event(event)

    async def run_scheduler(self):
        """定时调度器"""
        while True:
            # 检查定时任务
            schedules = await self.db.query("""
                SELECT * FROM hook_schedules
                WHERE enabled = true
                AND next_run <= time::now()
            """)

            for schedule in schedules:
                await self.execute_schedule(schedule)

            # 每分钟检查一次
            await asyncio.sleep(60)

    async def execute_schedule(self, schedule):
        """执行定时任务"""
        try:
            # 执行Hook脚本
            result = await self.execute_script(
                schedule["script"],
                {"schedule_id": schedule["id"]}
            )

            # 更新执行时间
            next_run = self.calculate_next_run(schedule["cron_expression"])
            await self.db.update("hook_schedules", {
                "id": schedule["id"],
                "last_run": datetime.now(),
                "next_run": next_run
            })

        except Exception as e:
            # 记录错误
            await self.record_error(schedule["id"], e)

    async def heartbeat(self):
        """心跳 - 每30分钟写入运行状态"""
        while True:
            await self.record_health_status()
            await asyncio.sleep(1800)  # 30分钟

    async def record_health_status(self):
        """记录运行状态"""
        await self.db.create("hook_health", {
            "timestamp": datetime.now(),
            "status": "running",
            "namespace": self.namespace
        })
```

## Webhook配置

### 微信Webhook
```yaml
wechat_webhook:
  enabled: true
  url: "${WECHAT_WEBHOOK_URL}"

  events:
    - task_completed
    - task_failed
    - daily_summary

  format: "markdown"
```

### 消息模板
```yaml
templates:
  task_completed:
    title: "任务完成 ✅"
    content: |
      任务: {task_name}
      耗时: {duration}
      Agent: {agent_id}

  task_failed:
    title: "任务失败 ❌"
    content: |
      任务: {task_name}
      错误: {error_message}
      Agent: {agent_id}

  daily_summary:
    title: "每日汇总 📊"
    content: |
      日期: {date}
      完成: {completed}
      失败: {failed}
      成功率: {success_rate}%
```

## 启动脚本

### Docker Compose
```yaml
version: '3.8'
services:
  surrealdb:
    image: surrealdb/surrealdb:latest
    container_name: ai_agents_surrealdb
    ports:
      - "11001:11001"
    environment:
      - SURREALDB_USER=root
      - SURREALDB_PASS=${SURREALDB_PASS}
    volumes:
      - surrealdb_data:/var/lib/surrealdb
    restart: unless-stopped

  hook-runtime:
    build: ./hook-runtime
    container_name: ai_agents_hook_runtime
    depends_on:
      - surrealdb
    environment:
      - SURREALDB_URL=ws://surrealdb:11001/rpc
      - SURREALDB_PASS=${SURREALDB_PASS}
      - SURREALDB_NAMESPACE=ai_agents_v2
    restart: unless-stopped

volumes:
  surrealdb_data:
```

### Windows服务配置
```powershell
# 创建Windows服务
New-Service -Name "AIAgentsHookRuntime" `
  -BinaryPathName "C:\ai-agents\hook-runtime.exe" `
  -DisplayName "AI Agents Hook Runtime" `
  -Description "AI Agent系统的Hook自动触发运行环境" `
  -StartupType Automatic
```
