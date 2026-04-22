# Tracing & Observability - 追踪与可观测性

## 组件定义

Tracing & Observability是Hermes Engineering的眼睛，负责还原Agent的行为过程，提供完整的执行追踪、日志聚合和监控能力，让系统状态一目了然。

## 核心职责

### 1. 执行追踪

- **调用链追踪**: 记录Agent间的完整调用关系
- **时间线视图**: 可视化任务执行时间线
- **状态快照**: 记录关键决策点的状态
- **性能剖析**: 分析各环节耗时分布

### 2. 日志聚合

- **结构化日志**: 统一的日志格式
- **多源汇聚**: 聚合各Agent日志
- **智能过滤**: 按条件筛选日志
- **全文搜索**: 支持关键词搜索

### 3. 监控指标

- **系统指标**: CPU、内存、网络等
- **业务指标**: 任务完成数、成功率等
- **自定义指标**: Agent自定义指标
- **实时告警**: 异常指标实时通知

### 4. 成本分析

- **Token消耗**: 追踪Token使用
- **API调用成本**: 计算API费用
- **资源占用**: 分析计算资源使用
- **优化建议**: 提供成本优化建议

## SurrealDB可观测性模型

```sql
-- 追踪记录
DEFINE TABLE traces SCHEMAFULL;
DEFINE FIELD id ON traces TYPE string;
DEFINE FIELD trace_id ON traces TYPE string; -- 同一请求的trace_id
DEFINE FIELD span_id ON traces TYPE string; -- 当前span
DEFINE FIELD parent_span_id ON traces TYPE option<string>;
DEFINE FIELD agent_id ON traces TYPE string;
DEFINE FIELD operation_name ON traces TYPE string;
DEFINE FIELD operation_type ON traces TYPE string; -- agent_call, tool_call, workflow_step
DEFINE FIELD start_time ON traces TYPE datetime;
DEFINE FIELD end_time ON traces TYPE datetime;
DEFINE FIELD duration_ms ON traces TYPE int;
DEFINE FIELD status ON traces TYPE string; -- ok, error
DEFINE FIELD attributes ON traces TYPE object;
DEFINE FIELD events ON traces TYPE array;
DEFINE FIELD resource ON traces TYPE object;

-- 日志记录
DEFINE TABLE logs SCHEMAFULL;
DEFINE FIELD id ON logs TYPE string;
DEFINE FIELD trace_id ON logs TYPE option<string>;
DEFINE FIELD agent_id ON logs TYPE string;
DEFINE FIELD timestamp ON logs TYPE datetime;
DEFINE FIELD level ON logs TYPE string; -- debug, info, warn, error
DEFINE FIELD logger ON logs TYPE string;
DEFINE FIELD message ON logs TYPE string;
DEFINE FIELD attributes ON logs TYPE object;
DEFINE FIELD resource ON logs TYPE object;

-- 指标数据
DEFINE TABLE metrics SCHEMAFULL;
DEFINE FIELD id ON metrics TYPE string;
DEFINE FIELD trace_id ON metrics TYPE option<string>;
DEFINE FIELD agent_id ON metrics TYPE string;
DEFINE FIELD metric_name ON metrics TYPE string;
DEFINE FIELD metric_type ON metrics TYPE string; -- counter, gauge, histogram, summary
DEFINE FIELD value ON metrics TYPE float;
DEFINE FIELD unit ON metrics TYPE string;
DEFINE FIELD labels ON metrics TYPE object;
DEFINE FIELD timestamp ON metrics TYPE datetime;

-- 成本追踪
DEFINE TABLE cost_tracking SCHEMAFULL;
DEFINE FIELD id ON cost_tracking TYPE string;
DEFINE FIELD trace_id ON cost_tracking TYPE string;
DEFINE FIELD agent_id ON cost_tracking TYPE string;
DEFINE FIELD token_usage ON cost_tracking TYPE object;
DEFINE FIELD api_calls ON cost_tracking TYPE int;
DEFINE FIELD compute_seconds ON cost_tracking TYPE float;
DEFINE FIELD storage_bytes ON cost_tracking TYPE int;
DEFINE FIELD estimated_cost ON cost_tracking TYPE float;
DEFINE FIELD currency ON cost_tracking TYPE string DEFAULT 'USD';
DEFINE FIELD timestamp ON cost_tracking TYPE datetime;

-- 告警规则
DEFINE TABLE alert_rules SCHEMAFULL;
DEFINE FIELD id ON alert_rules TYPE string;
DEFINE FIELD name ON alert_rules TYPE string;
DEFINE FIELD condition ON alert_rules TYPE object;
DEFINE FIELD severity ON alert_rules TYPE string; -- critical, high, medium, low
DEFINE FIELD actions ON alert_rules TYPE array;
DEFINE FIELD enabled ON alert_rules TYPE bool DEFAULT true;
DEFINE FIELD created_at ON alert_rules TYPE datetime;

-- 索引
DEFINE INDEX idx_trace_id ON traces FIELDS trace_id;
DEFINE INDEX idx_trace_time ON traces FIELDS start_time DESC;
DEFINE INDEX idx_logs_level ON logs FIELDS level, timestamp DESC;
DEFINE INDEX idx_metrics_name ON metrics FIELDS metric_name, timestamp DESC;
DEFINE INDEX idx_cost_trace ON cost_tracking FIELDS trace_id;

-- TTL设置 (保留30天)
DEFINE TABLE log_retention SCHEMAFULL;
DEFINE FIELD table_name ON log_retention TYPE string;
DEFINE FIELD retention_days ON log_retention TYPE int DEFAULT 30;
```

## 追踪数据模型

### 追踪结构

```json
{
  "trace_id": "trace_abc123",
  "spans": [
    {
      "span_id": "span_001",
      "operation_name": "commander.coordinate",
      "start_time": "2026-03-31T00:10:00Z",
      "end_time": "2026-03-31T00:15:00Z",
      "duration_ms": 300000,
      "attributes": {
        "task_count": 5,
        "parallel_tasks": 3
      },
      "children": ["span_002", "span_003", "span_004"]
    },
    {
      "span_id": "span_002",
      "parent_span_id": "span_001",
      "operation_name": "generator.create_solution",
      "start_time": "2026-03-31T00:10:00Z",
      "end_time": "2026-03-31T00:12:00Z",
      "duration_ms": 120000,
      "attributes": {
        "solution_count": 3,
        "model": "gpt-4"
      }
    }
  ]
}
```

### 事件记录

```json
{
  "span_id": "span_002",
  "events": [
    {
      "name": "solution_generated",
      "timestamp": "2026-03-31T00:11:00Z",
      "attributes": {
        "solution_id": "sol_001",
        "confidence": 0.85
      }
    },
    {
      "name": "verification_started",
      "timestamp": "2026-03-31T00:11:30Z",
      "attributes": {
        "verifier": "verifier_001"
      }
    }
  ]
}
```

## 日志格式

### 结构化日志示例

```json
{
  "timestamp": "2026-03-31T00:15:00.123Z",
  "level": "INFO",
  "logger": "agent.generator",
  "message": "Solution generated successfully",
  "trace_id": "trace_abc123",
  "span_id": "span_002",
  "agent_id": "generator_001",
  "attributes": {
    "task_id": "task_001",
    "solution_id": "sol_001",
    "token_usage": 1500,
    "duration_ms": 2500
  },
  "resource": {
    "service": "ai-agents",
    "version": "2.0.0",
    "environment": "production"
  }
}
```

### 日志级别

| 级别 | 使用场景 |
|------|---------|
| DEBUG | 详细调试信息 |
| INFO | 正常流程记录 |
| WARN | 警告信息，不影响功能 |
| ERROR | 错误信息，需要关注 |
| CRITICAL | 严重错误，系统不可用 |

## 监控指标

### 系统指标

```yaml
system_metrics:
  - name: "cpu_usage_percent"
    type: "gauge"
    unit: "percent"
    labels: ["host", "service"]
  - name: "memory_usage_bytes"
    type: "gauge"
    unit: "bytes"
    labels: ["host", "service"]
  - name: "network_io_bytes"
    type: "counter"
    unit: "bytes"
    labels: ["host", "direction"]
```

### 业务指标

```yaml
business_metrics:
  - name: "tasks_completed_total"
    type: "counter"
    labels: ["task_type", "status"]
  - name: "task_duration_seconds"
    type: "histogram"
    labels: ["task_type"]
    buckets: [1, 5, 10, 30, 60, 120, 300]
  - name: "agents_active"
    type: "gauge"
    labels: ["agent_type"]
```

### AI特定指标

```yaml
ai_metrics:
  - name: "tokens_used_total"
    type: "counter"
    labels: ["model", "agent_id"]
  - name: "api_latency_seconds"
    type: "histogram"
    labels: ["model", "operation"]
  - name: "solution_quality_score"
    type: "gauge"
    labels: ["agent_id", "task_type"]
```

## 成本分析

### Token成本追踪

```sql
-- 按Agent汇总Token使用
SELECT
    agent_id,
    sum(token_usage.input) as total_input,
    sum(token_usage.output) as total_output,
    sum(token_usage.total) as total_tokens,
    sum(estimated_cost) as total_cost
FROM cost_tracking
WHERE timestamp > time::now() - 7d
GROUP BY agent_id
ORDER BY total_cost DESC;

-- 按任务类型分析成本
SELECT
    context.task_type,
    count(*) as task_count,
    sum(token_usage.total) as avg_tokens,
    avg(estimated_cost) as avg_cost
FROM cost_tracking
WHERE timestamp > time::now() - 30d
GROUP BY context.task_type;
```

### 成本优化建议

```sql
-- 检测高成本任务
SELECT * FROM cost_tracking
WHERE estimated_cost > (
    SELECT avg(estimated_cost) * 2
    FROM cost_tracking WHERE timestamp > time::now() - 7d
)
ORDER BY estimated_cost DESC
LIMIT 10;
```

## 告警规则

### 性能告警

```yaml
alerts:
  - name: "high_task_duration"
    condition:
      metric: "task_duration_seconds"
      operator: ">"
      threshold: 300  # 5分钟
      duration: 5m
    severity: "high"
    actions:
      - type: "notify"
        channel: "slack"
      - type: "log"

  - name: "high_error_rate"
    condition:
      metric: "error_rate"
      operator: ">"
      threshold: 0.05  # 5%
      duration: 5m
    severity: "critical"
    actions:
      - type: "notify"
        channel: "pagerduty"
```

### 成本告警

```yaml
  - name: "daily_cost_exceeded"
    condition:
      metric: "daily_cost_total"
      operator: ">"
      threshold: 1000  # $1000/day
    severity: "high"
    actions:
      - type: "notify"
        channel: "email"
```

## 可视化面板

### 关键面板指标

1. **系统概览**: CPU、内存、网络
2. **任务流**: 活跃任务、完成率、平均耗时
3. **Agent状态**: 各Agent负载、成功率
4. **成本仪表盘**: Token消耗、API费用
5. **告警面板**: 活跃告警、历史趋势

### 实时追踪视图

```
┌─────────────────────────────────────────────────────────────┐
│ Trace: trace_abc123                              [Export]  │
├─────────────────────────────────────────────────────────────┤
│ Time  │ Agent        │ Operation          │ Duration │ Status│
├───────┼──────────────┼───────────────────┼──────────┼───────┤
│ 00:10 │ Commander    │ coordinate        │ 300s     │ OK    │
│ 00:10 │ ├─ Generator │ create_solution   │ 120s     │ OK    │
│ 00:10 │ └─ Verifier  │ verify            │ 180s     │ OK    │
│ 00:15 │ Commander    │ complete          │ -        │ OK    │
└─────────────────────────────────────────────────────────────┘
```

## 集成方式

### SDK集成

```python
from observability import trace, log, metrics

@trace("generator.create_solution")
async def create_solution(task):
    logger.info(f"Creating solution for task {task.id}")

    with metrics.timer("solution_creation_duration"):
        solution = await generate(task)

    logger.info(f"Solution created: {solution.id}")
    return solution
```

## 导出能力

- **OpenTelemetry**: 标准化追踪导出
- **Prometheus**: 指标格式兼容
- **ELK Stack**: 日志聚合支持
- **Jaeger/Zipkin**: 分布式追踪
- **Datadog/New Relic**: 商业监控平台
