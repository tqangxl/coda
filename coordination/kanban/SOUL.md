

# Kanban Board - 任务追踪看板

## 角色定义

Kanban是协调系统的可视化任务追踪组件，提供实时的任务状态看板，支持任务的流转管理和进度监控。

## 核心职责

### 1. 看板管理
- **列定义**: 定义看板的列（状态）
- **任务卡片**: 任务的可视化表示
- **拖拽操作**: 支持任务在列间移动
- **视图切换**: 不同视角的看板视图

### 2. 任务流转
- **状态管理**: 管理任务的状态转换
- **流转规则**: 定义状态转换规则
- **依赖追踪**: 管理任务间依赖
- **阻塞处理**: 处理阻塞的任务

### 3. 进度监控
- **统计面板**: 任务统计概览
- **瓶颈识别**: 识别流程瓶颈
- **周期分析**: 分析任务周期
- **趋势分析**: 分析趋势变化

## SurrealDB看板模型

```sql
-- 看板定义
DEFINE TABLE kanban_boards SCHEMAFULL;
DEFINE FIELD id ON kanban_boards TYPE string;
DEFINE FIELD name ON kanban_boards TYPE string;
DEFINE FIELD description ON kanban_boards TYPE string;
DEFINE FIELD owner ON kanban_boards TYPE string;
DEFINE FIELD columns ON kanban_boards TYPE array;
DEFINE FIELD swimlanes ON kanban_boards TYPE option<array>;
DEFINE FIELD settings ON kanban_boards TYPE object;
DEFINE FIELD created_at ON kanban_boards TYPE datetime;
DEFINE FIELD updated_at ON kanban_boards TYPE datetime;

-- 看板列
DEFINE TABLE kanban_columns SCHEMAFULL;
DEFINE FIELD id ON kanban_columns TYPE string;
DEFINE FIELD board_id ON kanban_columns TYPE string;
DEFINE FIELD name ON kanban_columns TYPE string;
DEFINE FIELD order ON kanban_columns TYPE int;
DEFINE FIELD color ON kanban_columns TYPE option<string>;
DEFINE FIELD wip_limit ON kanban_columns TYPE option<int>;
DEFINE FIELD rules ON kanban_columns TYPE object;

-- 任务卡片
DEFINE TABLE kanban_cards SCHEMAFULL;
DEFINE FIELD id ON kanban_cards TYPE string;
DEFINE FIELD board_id ON kanban_cards TYPE string;
DEFINE FIELD column_id ON kanban_cards TYPE string;
DEFINE FIELD title ON kanban_cards TYPE string;
DEFINE FIELD description ON kanban_cards TYPE option<string>;
DEFINE FIELD assignee ON kanban_cards TYPE option<string>;
DEFINE FIELD priority ON kanban_cards TYPE string;
DEFINE FIELD labels ON kanban_cards TYPE array;
DEFINE FIELD due_date ON kanban_cards TYPE option<datetime>;
DEFINE FIELD estimated_hours ON kanban_cards TYPE option<float>;
DEFINE FIELD actual_hours ON kanban_cards TYPE option<float>;
DEFINE FIELD attachments ON kanban_cards TYPE array;
DEFINE FIELD links ON kanban_cards TYPE array;
DEFINE FIELD subtasks ON kanban_cards TYPE array;
DEFINE FIELD order ON kanban_cards TYPE int;
DEFINE FIELD created_at ON kanban_cards TYPE datetime;
DEFINE FIELD updated_at ON kanban_cards TYPE datetime;

-- 卡片流转历史
DEFINE TABLE card_transitions SCHEMAFULL;
DEFINE FIELD id ON card_transitions TYPE string;
DEFINE FIELD card_id ON card_transitions TYPE string;
DEFINE FIELD from_column ON card_transitions TYPE string;
DEFINE FIELD to_column ON card_transitions TYPE string;
DEFINE FIELD triggered_by ON card_transitions TYPE string;
DEFINE FIELD reason ON card_transitions TYPE option<string>;
DEFINE FIELD timestamp ON card_transitions TYPE datetime;

-- 索引
DEFINE INDEX idx_card_board ON kanban_cards FIELDS board_id, column_id;
DEFINE INDEX idx_card_assignee ON kanban_cards FIELDS assignee, status;
DEFINE INDEX idx_transition_card ON card_transitions FIELDS card_id, timestamp DESC;
```

## 看板配置

### 默认列定义
```yaml
columns:
  - name: "TODO"
    color: "#gray"
    order: 1
    wip_limit: null
    rules:
      entry:
        - require_title
        - require_priority

  - name: "PROGRESS"
    color: "#blue"
    order: 2
    wip_limit: 5
    rules:
      entry:
        - require_assignee
      exit:
        - require_completion_notes

  - name: "REVIEW"
    color: "#yellow"
    order: 3
    wip_limit: 3
    rules:
      entry:
        - require_test_results

  - name: "DONE"
    color: "#green"
    order: 4
    wip_limit: null
    rules:
      auto_archive: 30  # 30天后自动归档
```

### 优先级定义
```yaml
priorities:
  CRITICAL:
    color: "#red"
    icon: "🚨"
    order: 1

  HIGH:
    color: "#orange"
    icon: "⬆️"
    order: 2

  MEDIUM:
    color: "#yellow"
    icon: "➡️"
    order: 3

  LOW:
    color: "#blue"
    icon: "⬇️"
    order: 4
```

## 看板操作

### 创建卡片
```python
async def create_card(self, card_data):
    """创建任务卡片"""
    # 1. 验证数据
    validation = self.validate_card(card_data)
    if not validation.valid:
        raise ValidationError(validation.errors)

    # 2. 获取默认列
    default_column = await self.get_default_column(card_data.board_id)

    # 3. 创建卡片
    card = await db.create("kanban_cards", {
        **card_data,
        "column_id": default_column.id,
        "order": await self.get_next_order(default_column.id),
        "created_at": datetime.now()
    })

    # 4. 记录流转
    await self.record_transition(
        card.id,
        None,
        default_column.id,
        "card_created"
    )

    # 5. 发布事件
    await event_bus.publish("card_created", card)

    return card
```

### 移动卡片
```python
async def move_card(self, card_id, to_column_id):
    """移动卡片到指定列"""
    # 1. 获取卡片和目标列
    card = await db.get("kanban_cards", card_id)
    to_column = await db.get("kanban_columns", to_column_id)
    from_column = await db.get("kanban_columns", card.column_id)

    # 2. 验证流转规则
    validation = await self.validate_transition(
        card,
        from_column,
        to_column
    )

    if not validation.valid:
        raise ValidationError(f"Cannot move: {validation.reason}")

    # 3. 检查WIP限制
    wip_check = await self.check_wip_limit(to_column)
    if not wip_check.valid:
        raise WIPLimitExceeded(to_column.name, wip_check.current)

    # 4. 更新卡片
    await db.update("kanban_cards", {
        "id": card_id,
        "column_id": to_column_id,
        "order": await self.get_next_order(to_column_id),
        "updated_at": datetime.now()
    })

    # 5. 记录流转
    await self.record_transition(
        card_id,
        from_column.id,
        to_column.id,
        "manual_move"
    )

    # 6. 发布事件
    await event_bus.publish("card_moved", {
        "card_id": card_id,
        "from": from_column.name,
        "to": to_column.name
    })
```

### WIP限制检查
```python
async def check_wip_limit(self, column):
    """检查WIP限制"""
    if not column.wip_limit:
        return {"valid": True}

    current_count = await db.count(
        "kanban_cards",
        {"column_id": column.id}
    )

    if current_count >= column.wip_limit:
        return {
            "valid": False,
            "current": current_count,
            "limit": column.wip_limit,
            "reason": f"WIP limit reached: {current_count}/{column.wip_limit}"
        }

    return {"valid": True}
```

## 看板视图

### 看板数据结构
```json
{
  "board": {
    "id": "board_001",
    "name": "AI Agent Tasks",
    "columns": [
      {
        "id": "col_001",
        "name": "TODO",
        "cards": [
          {
            "id": "card_001",
            "title": "实现用户认证",
            "priority": "HIGH",
            "assignee": "agent_coder",
            "labels": ["backend", "security"]
          }
        ]
      }
    ]
  }
}
```

### 统计视图
```json
{
  "statistics": {
    "total_cards": 45,
    "by_status": {
      "TODO": 12,
      "PROGRESS": 8,
      "REVIEW": 5,
      "DONE": 20
    },
    "by_assignee": {
      "agent_coder": 15,
      "agent_verifier": 10
    },
    "by_priority": {
      "CRITICAL": 3,
      "HIGH": 12,
      "MEDIUM": 20,
      "LOW": 10
    },
    "cycle_time": {
      "avg": 2.5,
      "median": 2.0,
      "p95": 5.0
    },
    "throughput": {
      "daily_avg": 3.5,
      "weekly_total": 24
    }
  }
}
```

## 实时同步

### Live Query订阅
```sql
-- 订阅看板更新
LIVE SELECT * FROM kanban_cards
WHERE board_id = $board_id
AND updated_at > time::now() - 5s;

-- 订阅统计更新
LIVE SELECT
    column_id,
    count(*) as count
FROM kanban_cards
WHERE board_id = $board_id
GROUP BY column_id;
```

## 看板API

### REST API端点
```
GET    /boards              # 获取所有看板
POST   /boards              # 创建看板
GET    /boards/:id          # 获取看板详情
PUT    /boards/:id          # 更新看板
DELETE /boards/:id          # 删除看板

GET    /boards/:id/cards     # 获取看板所有卡片
POST   /boards/:id/cards    # 创建卡片
GET    /boards/:id/cards/:card_id  # 获取卡片详情
PUT    /boards/:id/cards/:card_id  # 更新卡片
DELETE /boards/:id/cards/:card_id  # 删除卡片
PATCH  /boards/:id/cards/:card_id/move  # 移动卡片

GET    /boards/:id/stats     # 获取看板统计
GET    /boards/:id/analytics # 获取分析数据
```

## 瓶颈分析

```python
async def analyze_bottlenecks(self, board_id):
    """分析看板瓶颈"""
    # 1. 计算各列平均停留时间
    residence_times = await self.calculate_residence_times(board_id)

    # 2. 识别瓶颈列
    bottlenecks = []
    avg_time = sum(residence_times.values()) / len(residence_times)

    for column, time in residence_times.items():
        if time > avg_time * 1.5:
            bottlenecks.append({
                "column": column,
                "avg_residence_time": time,
                "deviation": time / avg_time,
                "suggestion": "检查该列的处理流程"
            })

    # 3. 分析WIP使用情况
    wip_usage = await self.analyze_wip_usage(board_id)

    return {
        "bottlenecks": bottlenecks,
        "wip_usage": wip_usage,
        "recommendations": self.generate_recommendations(
            bottlenecks,
            wip_usage
        )
    }
```

## 趋势分析

```sql
-- 每日吞吐量趋势
SELECT
    date_trunc('day', timestamp) as day,
    count(*) as cards_completed
FROM card_transitions
WHERE to_column = 'DONE'
AND timestamp > time::now() - 30d
GROUP BY day
ORDER BY day;

-- 周期时间趋势
SELECT
    date_trunc('week', timestamp) as week,
    avg(duration) as avg_cycle_time
FROM (
    SELECT
        card_id,
        min(timestamp) as start,
        max(timestamp) as end,
        (max(timestamp) - min(timestamp)) / 3600000 as duration
    FROM card_transitions
    WHERE to_column = 'DONE'
    AND timestamp > time::now() - 30d
    GROUP BY card_id
)
GROUP BY week;
```
