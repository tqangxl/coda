# Self-Improving - Hook 自动触发机制

## 角色定义

Hook是Self-Improving Agent的事件触发引擎，负责在特定事件发生时自动触发学习流程，实现持续改进。

## 核心职责

### 1. 事件监控
- **系统事件**: 监控任务执行、系统状态变化
- **用户事件**: 监控用户反馈、请求模式
- **外部事件**: 监控外部数据、API响应
- **定时事件**: 定期触发的学习任务

### 2. 条件匹配
- **规则引擎**: 评估触发条件
- **复杂条件**: 支持AND/OR/NOT组合条件
- **阈值触发**: 支持数值阈值条件
- **时间条件**: 支持时间窗口条件

### 3. 动作执行
- **学习动作**: 触发知识提取
- **通知动作**: 发送通知
- **自动化动作**: 执行系统操作
- **回调动作**: 调用其他Agent

## SurrealDB Hook配置

```sql
-- Hook定义
DEFINE TABLE hooks SCHEMAFULL;
DEFINE FIELD id ON hooks TYPE string;
DEFINE FIELD name ON hooks TYPE string;
DEFINE FIELD description ON hooks TYPE string;
DEFINE FIELD event_type ON hooks TYPE string;
DEFINE FIELD conditions ON hooks TYPE object;
DEFINE FIELD actions ON hooks TYPE array;
DEFINE FIELD priority ON hooks TYPE int DEFAULT 0;
DEFINE FIELD enabled ON hooks TYPE bool DEFAULT true;
DEFINE FIELD created_at ON hooks TYPE datetime;
DEFINE FIELD updated_at ON hooks TYPE datetime;

-- Hook执行记录
DEFINE TABLE hook_executions SCHEMAFULL;
DEFINE FIELD id ON hook_executions TYPE string;
DEFINE FIELD hook_id ON hook_executions TYPE string;
DEFINE FIELD trigger_event ON hook_executions TYPE object;
DEFINE FIELD conditions_met ON hook_executions TYPE array;
DEFINE FIELD actions_executed ON hook_executions TYPE array;
DEFINE FIELD result ON hook_executions TYPE string;
DEFINE FIELD duration_ms ON hook_executions TYPE int;
DEFINE FIELD executed_at ON hook_executions TYPE datetime;

-- 事件类型定义
DEFINE TABLE event_types SCHEMAFULL;
DEFINE FIELD name ON event_types TYPE string;
DEFINE FIELD description ON event_types TYPE string;
DEFINE FIELD schema ON event_types TYPE object;
DEFINE FIELD source ON event_types TYPE array;
```

## 事件类型

### 系统事件
```yaml
system_events:
  - name: "task_started"
    description: "任务开始执行"
    data:
      - task_id
      - task_type
      - agent_id

  - name: "task_completed"
    description: "任务完成"
    data:
      - task_id
      - duration
      - success
      - output

  - name: "task_failed"
    description: "任务失败"
    data:
      - task_id
      - error_type
      - error_message

  - name: "agent_loaded"
    description: "Agent加载"
```

### 用户事件
```yaml
user_events:
  - name: "feedback_received"
    description: "收到用户反馈"
    data:
      - task_id
      - rating
      - comment

  - name: "request_pattern"
    description: "请求模式识别"
    data:
      - pattern_type
      - frequency

  - name: "preference_changed"
    description: "偏好变化"
    data:
      - preference_type
      - old_value
      - new_value
```

## 条件表达式

### 简单条件
```yaml
conditions:
  - field: "success"
    operator: "eq"
    value: true

  - field: "duration"
    operator: "gt"
    value: 300

  - field: "error_type"
    operator: "in"
    value: ["timeout", "network_error"]
```

### 复合条件
```yaml
conditions:
  operator: "AND"
  conditions:
    - field: "success"
      operator: "eq"
      value: false
    - operator: "OR"
      conditions:
        - field: "error_type"
          operator: "eq"
          value: "validation_error"
        - field: "retry_count"
          operator: "gt"
          value: 2
```

### 聚合条件
```yaml
conditions:
  type: "aggregate"
  window: "1h"
  metric: "failure_count"
  operator: "gt"
  value: 5
```

## 动作类型

### 学习动作
```python
LEARNING_ACTIONS = {
    "extract_success_pattern": {
        "type": "learning",
        "subtype": "pattern_extraction",
        "target": "knowledge_base"
    },
    "analyze_failure": {
        "type": "learning",
        "subtype": "root_cause_analysis",
        "target": "lessons_learned"
    },
    "update_profile": {
        "type": "learning",
        "subtype": "profile_update",
        "target": "user_profile"
    }
}
```

### 通知动作
```python
NOTIFICATION_ACTIONS = {
    "notify_failure": {
        "type": "notification",
        "channel": "slack",
        "template": "failure_alert",
        "recipients": ["oncall"]
    },
    "log_event": {
        "type": "notification",
        "channel": "log",
        "level": "info"
    }
}
```

### 自动化动作
```python
AUTOMATION_ACTIONS = {
    "retry_task": {
        "type": "automation",
        "action": "retry",
        "max_attempts": 3
    },
    "scale_agent": {
        "type": "automation",
        "action": "scale",
        "agent_type": "generator",
        "delta": 1
    }
}
```

## Hook执行器

```python
class HookEngine:
    async def process_event(self, event):
        """处理事件"""
        # 1. 查找匹配的Hook
        matching_hooks = await self.find_matching_hooks(event)

        # 2. 按优先级排序
        sorted_hooks = sorted(
            matching_hooks,
            key=lambda h: h.priority,
            reverse=True
        )

        # 3. 执行Hook
        results = []
        for hook in sorted_hooks:
            result = await self.execute_hook(hook, event)
            results.append(result)

        return results

    async def execute_hook(self, hook, event):
        """执行单个Hook"""
        execution = {
            "hook_id": hook.id,
            "trigger_event": event,
            "start_time": datetime.now()
        }

        try:
            # 评估条件
            conditions_met = await self.evaluate_conditions(
                hook.conditions,
                event
            )

            if not conditions_met:
                return {"status": "skipped", "reason": "conditions_not_met"}

            execution["conditions_met"] = conditions_met

            # 执行动作
            actions_executed = []
            for action in hook.actions:
                result = await self.execute_action(action, event)
                actions_executed.append(result)

            execution["actions_executed"] = actions_executed
            execution["status"] = "success"

        except Exception as e:
            execution["status"] = "error"
            execution["error"] = str(e)

        finally:
            execution["duration_ms"] = (
                datetime.now() - execution["start_time"]
            ).total_seconds() * 1000
            await self.save_execution(execution)

        return execution
```

## 内置Hook示例

### 成功经验Hook
```yaml
hook:
  name: "extract_success_pattern"
  event_type: "task_completed"
  conditions:
    - field: "success"
      operator: "eq"
      value: true
    - field: "duration"
      operator: "gt"
      value: 60
  actions:
    - type: "learning"
      subtype: "extract_pattern"
      data:
        min_success_rate: 0.8
  priority: 10
  enabled: true
```

### 连续失败Hook
```yaml
hook:
  name: "alert_continuous_failures"
  event_type: "task_failed"
  conditions:
    type: "aggregate"
    window: "10m"
    metric: "failure_count"
    operator: "gte"
    value: 5
  actions:
    - type: "notification"
      channel: "slack"
      message: "检测到连续失败"
    - type: "learning"
      subtype: "root_cause_analysis"
  priority: 100
  enabled: true
```

### 性能下降Hook
```yaml
hook:
  name: "detect_performance_degradation"
  event_type: "task_completed"
  conditions:
    type: "trend"
    metric: "duration"
    direction: "increasing"
    window: "1h"
    threshold: 0.2
  actions:
    - type: "notification"
      channel: "alert"
      message: "性能下降趋势"
    - type: "learning"
      subtype: "analyze_performance"
  priority: 50
  enabled: true
```

## Hook管理

### 启用/禁用
```python
async def toggle_hook(self, hook_id, enabled):
    """切换Hook状态"""
    await db.update(
        "hooks",
        {"id": hook_id, "enabled": enabled}
    )
```

### 批量执行测试
```python
async def test_hooks(self, test_event):
    """测试Hook配置"""
    results = []
    for hook in await self.get_all_hooks():
        if hook.enabled:
            result = await self.evaluate_conditions(
                hook.conditions,
                test_event
            )
            results.append({
                "hook": hook.name,
                "would_trigger": result
            })
    return results
```

## 与学习系统集成

```python
# Hook触发学习
async def on_hook_triggered(self, hook_execution):
    """Hook被触发时的回调"""
    for action in hook_execution.actions_executed:
        if action.type == "learning":
            await learning.trigger_learning(
                learning_type=action.subtype,
                context=action.data,
                source_event=hook_execution.trigger_event
            )
```
