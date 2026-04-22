# Skill Creator - Executor 执行器

## 角色定义

Executor是Skill Creator内部的核心执行Agent，负责实际运行技能生成和测试任务。它是最直接与外部环境交互的Agent。

## 核心职责

### 1. 任务执行
- **技能生成**: 运行CREATE模式的技能生成逻辑
- **测试执行**: 运行EVAL模式的测试用例
- **改进应用**: 执行IMPROVE模式的改进措施
- **基准对比**: 执行BENCHMARK模式的对比任务

### 2. 环境管理
- **环境准备**: 准备测试所需的环境
- **资源分配**: 分配执行所需的计算资源
- **状态监控**: 监控执行状态和进度
- **资源清理**: 执行完成后清理资源

### 3. 结果收集
- **执行日志**: 收集执行过程中的日志
- **性能指标**: 收集执行性能数据
- **错误信息**: 收集执行中的错误信息
- **输出结果**: 收集任务的输出结果

## SurrealDB模型

```sql
-- 执行任务表
DEFINE TABLE executor_tasks SCHEMAFULL;
DEFINE FIELD id ON executor_tasks TYPE string;
DEFINE FIELD task_type ON executor_tasks TYPE string;
DEFINE FIELD mode ON executor_tasks TYPE string;
DEFINE FIELD input ON executor_tasks TYPE object;
DEFINE FIELD output ON executor_tasks TYPE option<object>;
DEFINE FIELD status ON executor_tasks TYPE string DEFAULT 'pending';
DEFINE FIELD error ON executor_tasks TYPE option<object>;
DEFINE FIELD progress ON executor_tasks TYPE float DEFAULT 0;
DEFINE FIELD started_at ON executor_tasks TYPE option<datetime>;
DEFINE FIELD completed_at ON executor_tasks TYPE option<datetime>;
DEFINE FIELD created_at ON executor_tasks TYPE datetime;

-- 执行日志
DEFINE TABLE executor_logs SCHEMAFULL;
DEFINE FIELD id ON executor_logs TYPE string;
DEFINE FIELD task_id ON executor_logs TYPE string;
DEFINE FIELD level ON executor_logs TYPE string;
DEFINE FIELD message ON executor_logs TYPE string;
DEFINE FIELD metadata ON executor_logs TYPE object;
DEFINE FIELD timestamp ON executor_logs TYPE datetime;

-- 执行指标
DEFINE TABLE executor_metrics SCHEMAFULL;
DEFINE FIELD id ON executor_metrics TYPE string;
DEFINE FIELD task_id ON executor_metrics TYPE string;
DEFINE FIELD metric_name ON executor_metrics TYPE string;
DEFINE FIELD metric_value ON executor_metrics TYPE float;
DEFINE FIELD unit ON executor_metrics TYPE string;
DEFINE FIELD timestamp ON executor_metrics TYPE datetime;

-- 索引
DEFINE INDEX idx_task_status ON executor_tasks FIELDS status, created_at DESC;
DEFINE INDEX idx_task_mode ON executor_tasks FIELDS mode, status;
```

## 执行流程

```python
class Executor:
    async def execute(self, task):
        # 1. 任务验证
        if not self.validate_task(task):
            raise ValidationError("Invalid task")

        # 2. 环境准备
        context = await self.prepare_environment(task)

        # 3. 执行任务
        try:
            result = await self.run_task(task, context)

            # 4. 收集结果
            await self.collect_results(task.id, result)

            return result
        except Exception as e:
            await self.handle_error(task.id, e)
            raise
        finally:
            # 5. 清理资源
            await self.cleanup(context)
```

## 执行策略

### 并行执行
```python
async def execute_parallel(self, tasks):
    """并行执行多个任务"""
    results = await asyncio.gather(*[
        self.execute(task) for task in tasks
    ], return_exceptions=True)
    return results
```

### 串行执行
```python
async def execute_sequential(self, tasks):
    """串行执行多个任务"""
    results = []
    for task in tasks:
        result = await self.execute(task)
        results.append(result)
    return results
```

### 批量执行
```python
async def execute_batch(self, tasks, batch_size=5):
    """批量执行，控制并发"""
    results = []
    for i in range(0, len(tasks), batch_size):
        batch = tasks[i:i+batch_size]
        batch_results = await self.execute_parallel(batch)
        results.extend(batch_results)
    return results
```

## 执行状态机

```
PENDING → RUNNING → COMPLETED
              ↓
           FAILED ←──→ RETRYING
```

### 状态转换规则
| 当前状态 | 事件 | 下一状态 | 条件 |
|---------|------|---------|------|
| PENDING | start | RUNNING | 资源可用 |
| RUNNING | complete | COMPLETED | 执行成功 |
| RUNNING | error | FAILED | 不可恢复错误 |
| RUNNING | timeout | FAILED | 超时 |
| FAILED | retry | RETRYING | 重试次数<上限 |
| RETRYING | start | RUNNING | 重试开始 |
| RETRYING | max_retry | FAILED | 重试次数超限 |

## 执行日志

```json
{
  "log_id": "log_xxx",
  "task_id": "task_001",
  "level": "INFO",
  "message": "Task execution started",
  "metadata": {
    "mode": "create",
    "agent_id": "executor_001"
  },
  "timestamp": "2026-03-31T00:10:00Z"
}
```

## 性能指标

| 指标 | 说明 | 阈值 |
|------|------|------|
| execution_duration | 执行时长 | < 300s |
| token_usage | Token消耗 | < 10000 |
| memory_usage | 内存使用 | < 512MB |
| api_calls | API调用次数 | < 50 |

## 错误处理

```python
ERROR_HANDLERS = {
    "ValidationError": {
        "action": "fail",
        "retry": False
    },
    "TimeoutError": {
        "action": "retry",
        "max_retries": 3,
        "backoff": "exponential"
    },
    "RateLimitError": {
        "action": "retry",
        "max_retries": 5,
        "backoff": "linear",
        "delay": 60
    },
    "ExecutionError": {
        "action": "retry",
        "max_retries": 2,
        "backoff": "immediate"
    }
}
```

## 与其他Agent协作

| Agent | 协作方式 |
|-------|---------|
| Grader | 接收评分任务 |
| Comparator | 接收对比任务 |
| Analyzer | 提供分析数据 |
