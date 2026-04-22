

# Cost Tracking - 成本追踪

## 角色定义

Cost Tracking是协调系统的成本监控组件，负责追踪和分析Agent执行任务的资源消耗，提供成本优化建议。

## 核心职责

### 1. 成本采集
- **Token消耗**: 追踪AI API的Token使用
- **计算资源**: 追踪CPU、内存使用
- **存储使用**: 追踪存储资源
- **网络流量**: 追踪数据传输

### 2. 成本分析
- **实时计算**: 实时计算当前成本
- **历史分析**: 分析历史成本趋势
- **归因分析**: 将成本归因到具体任务/Agent
- **预算监控**: 监控预算使用情况

### 3. 成本优化
- **异常检测**: 检测异常成本消耗
- **优化建议**: 提供成本优化建议
- **预测分析**: 预测未来成本趋势
- **预算告警**: 预算超支预警

## SurrealDB成本模型

```sql
-- 成本记录
DEFINE TABLE cost_records SCHEMAFULL;
DEFINE FIELD id ON cost_records TYPE string;
DEFINE FIELD trace_id ON cost_records TYPE string;
DEFINE FIELD agent_id ON cost_records TYPE string;
DEFINE FIELD task_id ON cost_records TYPE option<string>;
DEFINE FIELD cost_type ON cost_records TYPE string;
DEFINE FIELD resource_type ON cost_records TYPE string;
DEFINE FIELD quantity ON cost_records TYPE float;
DEFINE FIELD unit_price ON cost_records TYPE float;
DEFINE FIELD total_cost ON cost_records TYPE float;
DEFINE FIELD currency ON cost_records TYPE string DEFAULT 'USD';
DEFINE FIELD metadata ON cost_records TYPE object;
DEFINE FIELD timestamp ON cost_records TYPE datetime;

-- 预算配置
DEFINE TABLE budgets SCHEMAFULL;
DEFINE FIELD id ON budgets TYPE string;
DEFINE FIELD name ON budgets TYPE string;
DEFINE FIELD scope ON cost_records TYPE string;
DEFINE FIELD scope_id ON cost_records TYPE option<string>;
DEFINE FIELD amount ON budgets TYPE float;
DEFINE FIELD period ON budgets TYPE string;
DEFINE FIELD start_date ON budgets TYPE datetime;
DEFINE FIELD end_date ON budgets TYPE datetime;
DEFINE FIELD alert_threshold ON budgets TYPE float DEFAULT 0.8;
DEFINE FIELD created_at ON budgets TYPE datetime;

-- 成本聚合
DEFINE TABLE cost_aggregates SCHEMAFULL;
DEFINE FIELD id ON cost_aggregates TYPE string;
DEFINE FIELD period ON cost_aggregates TYPE string;
DEFINE FIELD group_by ON cost_aggregates TYPE string;
DEFINE FIELD group_value ON cost_aggregates TYPE string;
DEFINE FIELD total_cost ON cost_aggregates TYPE float;
DEFINE FIELD token_count ON cost_aggregates TYPE int;
DEFINE FIELD compute_hours ON cost_aggregates TYPE float;
DEFINE FIELD request_count ON cost_aggregates TYPE int;
DEFINE FIELD avg_cost_per_request ON cost_aggregates TYPE float;
DEFINE FIELD calculated_at ON cost_aggregates TYPE datetime;

-- 成本异常
DEFINE TABLE cost_anomalies SCHEMAFULL;
DEFINE FIELD id ON cost_anomalies TYPE string;
DEFINE FIELD anomaly_type ON cost_anomalies TYPE string;
DEFINE FIELD severity ON cost_anomalies TYPE string;
DEFINE FIELD description ON cost_anomalies TYPE string;
DEFINE FIELD affected_resources ON cost_anomalies TYPE array;
DEFINE FIELD expected_cost ON cost_anomalies TYPE float;
DEFINE FIELD actual_cost ON cost_anomalies TYPE float;
DEFINE FIELD deviation ON cost_anomalies TYPE float;
DEFINE FIELD detected_at ON cost_anomalies TYPE datetime;
DEFINE FIELD status ON cost_anomalies TYPE string DEFAULT 'open';
DEFINE FIELD resolved_at ON cost_anomalies TYPE option<datetime>;

-- 索引
DEFINE INDEX idx_cost_agent ON cost_records FIELDS agent_id, timestamp DESC;
DEFINE INDEX idx_cost_task ON cost_records FIELDS task_id, timestamp;
DEFINE INDEX idx_cost_type ON cost_records FIELDS cost_type, timestamp;
```

## 成本类型

### Token成本
```yaml
token_costs:
  gpt_4:
    input: 0.03  # per 1K tokens
    output: 0.06
    batch_input: 0.015
    batch_output: 0.03

  gpt_35_turbo:
    input: 0.0005
    output: 0.0015

  claude_3:
    input: 0.015
    output: 0.075
```

### 计算成本
```yaml
compute_costs:
  per_cpu_hour: 0.016  # $0.016 per vCPU-hour
  per_memory_gb_hour: 0.002  # $0.002 per GB-hour
  per_gpu_hour: 0.95  # GPU instances
```

### 存储成本
```yaml
storage_costs:
  per_gb_month: 0.023  # S3 standard
  per_request: 0.0004  # per 1K requests
```

## 成本采集

### Token采集
```python
async def record_token_usage(self, usage_data):
    """记录Token使用"""
    cost = self.calculate_token_cost(usage_data)

    await db.create("cost_records", {
        "id": f"cost_{uuid()}",
        "trace_id": usage_data.trace_id,
        "agent_id": usage_data.agent_id,
        "task_id": usage_data.task_id,
        "cost_type": "token",
        "resource_type": usage_data.model,
        "quantity": usage_data.total_tokens,
        "unit_price": cost.unit_price,
        "total_cost": cost.total,
        "metadata": {
            "input_tokens": usage_data.input_tokens,
            "output_tokens": usage_data.output_tokens,
            "model": usage_data.model
        },
        "timestamp": datetime.now()
    })

    # 检查预算
    await self.check_budget(usage_data.agent_id)
```

### 成本计算
```python
PRICING = {
    "gpt-4": {
        "input": 0.03 / 1000,
        "output": 0.06 / 1000
    },
    "claude-3": {
        "input": 0.015 / 1000,
        "output": 0.075 / 1000
    }
}

def calculate_token_cost(self, usage):
    """计算Token成本"""
    model_pricing = PRICING.get(usage.model, {})

    input_cost = usage.input_tokens * model_pricing.get("input", 0)
    output_cost = usage.output_tokens * model_pricing.get("output", 0)

    return {
        "input_cost": input_cost,
        "output_cost": output_cost,
        "total": input_cost + output_cost,
        "unit_price": (input_cost + output_cost) / usage.total_tokens if usage.total_tokens > 0 else 0
    }
```

## 成本分析

### 成本归因
```python
async def attribute_costs(self, time_range):
    """成本归因分析"""
    # 按Agent归因
    by_agent = await db.query("""
        SELECT
            agent_id,
            sum(total_cost) as total,
            count(*) as request_count
        FROM cost_records
        WHERE timestamp > $start AND timestamp < $end
        GROUP BY agent_id
        ORDER BY total DESC
    """, {"start": time_range.start, "end": time_range.end})

    # 按任务类型归因
    by_task_type = await db.query("""
        SELECT
            metadata.task_type as task_type,
            sum(total_cost) as total,
            count(*) as count,
            avg(total_cost) as avg_cost
        FROM cost_records
        WHERE timestamp > $start AND timestamp < $end
        GROUP BY task_type
    """, {"start": time_range.start, "end": time_range.end})

    # 按时间归因
    by_hour = await db.query("""
        SELECT
            date_trunc('hour', timestamp) as hour,
            sum(total_cost) as total
        FROM cost_records
        WHERE timestamp > $start AND timestamp < $end
        GROUP BY hour
        ORDER BY hour
    """, {"start": time_range.start, "end": time_range.end})

    return {
        "by_agent": by_agent,
        "by_task_type": by_task_type,
        "by_hour": by_hour
    }
```

### 成本趋势
```sql
-- 每日成本趋势
SELECT
    date_trunc('day', timestamp) as day,
    sum(total_cost) as total_cost,
    sum(quantity) FILTER WHERE cost_type = 'token' as token_usage,
    count(*) as request_count
FROM cost_records
WHERE timestamp > time::now() - 30d
GROUP BY day
ORDER BY day;

-- 环比增长率
WITH daily_costs AS (
    SELECT
        date_trunc('day', timestamp) as day,
        sum(total_cost) as cost
    FROM cost_records
    WHERE timestamp > time::now() - 14d
    GROUP BY day
)
SELECT
    day,
    cost,
    lag(cost) as prev_day_cost,
    (cost - lag(cost)) / lag(cost) * 100 as growth_rate
FROM daily_costs
ORDER BY day;
```

## 预算监控

### 预算检查
```python
async def check_budget(self, agent_id):
    """检查预算使用情况"""
    # 获取当前预算
    budget = await self.get_active_budget(agent_id)

    if not budget:
        return  # 无预算限制

    # 计算已使用金额
    spent = await self.calculate_spent(
        budget.scope,
        budget.scope_id,
        budget.start_date,
        datetime.now()
    )

    usage_ratio = spent / budget.amount

    # 检查是否超过阈值
    if usage_ratio >= 1.0:
        await self.notify_budget_exceeded(budget, spent)
        raise BudgetExceededError(budget.name, spent, budget.amount)

    elif usage_ratio >= budget.alert_threshold:
        await self.notify_budget_warning(budget, spent, usage_ratio)
```

### 预算告警
```python
async def notify_budget_warning(self, budget, spent, ratio):
    """发送预算告警"""
    message = {
        "type": "budget_warning",
        "budget_name": budget.name,
        "spent": spent,
        "limit": budget.amount,
        "usage_ratio": ratio,
        "remaining": budget.amount - spent,
        "period": budget.period
    }

    # 发送通知
    await notification_service.send(
        channels=["slack", "email"],
        recipients=["cost-team"],
        message=message
    )
```

## 异常检测

### 检测规则
```yaml
anomaly_detection:
  sudden_spike:
    condition: "current_cost > avg_cost * 3"
    severity: "high"
    window: "1h"

  unusual_pattern:
    condition: "cost_distribution changed significantly"
    severity: "medium"
    window: "24h"

  budget_exceeded:
    condition: "cumulative_cost > budget_limit"
    severity: "critical"
```

### 检测实现
```python
async def detect_anomalies(self):
    """检测成本异常"""
    anomalies = []

    # 1. 突发峰值检测
    spike_anomalies = await self.detect_sudden_spikes()
    anomalies.extend(spike_anomalies)

    # 2. 模式异常检测
    pattern_anomalies = await self.detect_pattern_anomalies()
    anomalies.extend(pattern_anomalies)

    # 3. 记录异常
    for anomaly in anomalies:
        await db.create("cost_anomalies", {
            **anomaly,
            "id": f"anomaly_{uuid()}",
            "detected_at": datetime.now()
        })

        # 发送告警
        await self.alert_anomaly(anomaly)

    return anomalies
```

## 成本报告

```json
{
  "report_id": "cost_report_2026w13",
  "period": "2026-03-24 to 2026-03-30",
  "total_cost": 1250.50,
  "currency": "USD",

  "summary": {
    "token_cost": 980.30,
    "compute_cost": 220.00,
    "storage_cost": 50.20
  },

  "by_agent": [
    {
      "agent_id": "generator",
      "cost": 450.00,
      "share": 0.36
    },
    {
      "agent_id": "verifier",
      "cost": 380.00,
      "share": 0.30
    }
  ],

  "trends": {
    "vs_last_week": 0.12,
    "vs_last_month": -0.05
  },

  "top_cost_drivers": [
    {
      "task_id": "task_xxx",
      "cost": 45.00,
      "reason": "Large context usage"
    }
  ],

  "recommendations": [
    {
      "priority": "high",
      "action": "Optimize context size for generator",
      "potential_savings": 150.00
    }
  ]
}
```

## 优化建议

```python
async def generate_optimization_suggestions(self):
    """生成优化建议"""
    suggestions = []

    # 1. Token优化
    large_contexts = await self.find_large_context_usage()
    if large_contexts:
        suggestions.append({
            "category": "token",
            "priority": "high",
            "title": "Reduce large context usage",
            "details": f"Found {len(large_contexts)} tasks with context > 100K tokens",
            "potential_savings": self.estimate_savings(large_contexts, "context_trimming")
        })

    # 2. 模型选择
    inefficient_models = await self.find_inefficient_model_usage()
    if inefficient_models:
        suggestions.append({
            "category": "model",
            "priority": "medium",
            "title": "Use smaller models for simple tasks",
            "details": "Some tasks could use gpt-3.5-turbo instead of gpt-4",
            "potential_savings": self.estimate_savings(inefficient_models, "model_downgrade")
        })

    # 3. 缓存建议
    cache_opportunities = await self.find_cache_opportunities()
    if cache_opportunities:
        suggestions.append({
            "category": "caching",
            "priority": "medium",
            "title": "Enable result caching",
            "details": "Found repeated queries that could be cached",
            "potential_savings": self.estimate_savings(cache_opportunities, "caching")
        })

    return suggestions
```

## 实时仪表板

### 关键指标
| 指标 | 说明 | 刷新频率 |
|------|------|---------|
| 当前成本 | 当前小时/天的总成本 | 1分钟 |
| 预算使用率 | 预算已使用百分比 | 5分钟 |
| Token使用量 | 输入/输出Token数量 | 1分钟 |
| 成本趋势 | 成本随时间变化 | 15分钟 |
| Top消费者 | 成本最高的Agent/任务 | 15分钟 |

### 告警规则
```yaml
alerts:
  - name: "hourly_budget_80"
    condition: "hourly_cost >= budget * 0.8"
    severity: "warning"

  - name: "daily_budget_100"
    condition: "daily_cost >= budget"
    severity: "critical"

  - name: "cost_spike"
    condition: "hourly_cost > avg_hourly_cost * 3"
    severity: "critical"
```
