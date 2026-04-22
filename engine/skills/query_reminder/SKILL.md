---
name: query-reminder
description: >
  查询 SurrealDB 中的日程 (v2_schedules)、待办任务 (v2_tasks) 和系统任务 (tasks)。
  当用户提到"查询提醒"、"今天有什么活"、"待办"、"日程"时触发。
allowed-tools:
  - bash
  - read
---

# 查询提醒 (Query Reminder)

在 SurrealDB (`127.0.0.1:11001`, ns: `ai_agents_v2`, db: `agent_system`) 中
聚合查询今日日程、进行中任务和系统级待办，输出结构化报告。

## 触发条件

- 用户说 "查询提醒"
- 用户说 "今天有什么活"
- 用户说 "待办任务"
- 每次会话开始时的自我感知协议 (Step 4)
- 用户说 "提醒" 或 "schedule" 或 "tasks"

## 执行步骤

### 1. 确认 SurrealDB 在线

```
检查 SurrealDB 进程是否存在 (surreal.exe)。
如果不在线:
  - 运行 startup.ps1 -Console 拉起服务
  - 等待 5 秒确认端口 11001 可达
如果在线: 继续
```

### 2. 连接数据库并查询

```python
# 使用 AsyncSurreal (不是 Surreal!)
from surrealdb import AsyncSurreal

db = AsyncSurreal("ws://127.0.0.1:11001/rpc")
await db.connect()
await db.signin({"user": "root", "pass": "<from_env>"})
await db.use("ai_agents_v2", "agent_system")  # 注意: agent_system, 不是 agent_system_v2

工厂模式验证：AsyncSurreal(url) 确实是一个工厂函数，它根据 URL 协议返回 AsyncWsSurrealConnection 或其他连接实例。
连接行为：await db.connect() 不需要再次传入 URL（构造函数已处理），这证实了我之前的修正。
自动拆包逻辑：源码中 query() 方法内部会自动执行 response["result"][0]["result"]，这意味着它默认返回第一条语句的结果。凭据参数：signin 接受一个 vars 字典，参数名与我们代码中的 {"user": ..., "pass": ...} 完全匹配。
# 查询三张表:
# 1. v2_schedules — 今日日程
# 2. tasks — 进行中/待办任务/系统级任务
```

### 3. 格式化输出

```markdown
### 🔍 今日提醒 (YYYY-MM-DD HH:MM)

| 类型 | 状态 | 内容 | 优先级 |
|:---|:---|:---|:---|
| 日程 | ... | ... | ... |
| 待办 | ... | ... | ... |
| 系统 | ... | ... | ... |
```

### 4. 处理异常

```
如果 SurrealDB 不可达:
  → 报告 "⚠️ SurrealDB 离线, 无法查询提醒。请运行 startup.ps1 -Console"
如果表不存在:
  → 报告 "(暂无XXX数据)" 而不是报错
如果查询结果为空:
  → 报告 "(暂无今日日程/待办)" — 这是正常状态
```

## 注意事项

- 永远用 `127.0.0.1` 不用 `localhost`
- 永远用 `AsyncSurreal` 不用 `Surreal` (后者不支持 async with)
- 数据库名是 `agent_system` (不是 `agent_system_v2`, v2 是空库)
- SDK 结果解析要做多路兼容 (见 LEARNINGS.md)
- 查询失败不应阻断主流程, 静默降级
