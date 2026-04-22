# Generator Agent - Agent配置

## 基本信息

```yaml
agent:
  id: "generator"
  name: "Generator"
  type: "generator"
  version: "2.0.0"
  namespace: "ai_agents_v2"
```

## 职责

- 方案生成与创新思维
- 多方案并行生成
- 与Verifier对抗迭代

## cx优化配置

```yaml
cx_config:
  enabled: true

  before_llm_call:
    - command: "symbols"
      reason: "了解现有代码符号"
    - command: "overview"
      reason: "了解代码结构"
    - command: "references"
      reason: "追踪相关引用"

  token_budget:
    max: 6000
    reserve: 1000  # 保留给LLM响应
```

## 记忆配置

```yaml
memory:
  type: "private"
  table: "generator_memory"

  stores:
    - type: "solution_patterns"
      ttl: "30d"
    - type: "successful_approaches"
      ttl: "7d"
    - type: "failed_attempts"
      ttl: "7d"
```

## 任务队列

```yaml
tasks:
  input_queue: "generator_inbox"
  output_queue: "generator_outbox"

  pattern:
    parallel_generation: 3  # 每次生成3个方案
    max_iterations: 5       # 最多5次迭代
```

## SurrealDB表

```sql
-- Generator专用表
DEFINE TABLE generator_memory SCHEMAFULL;
DEFINE FIELD agent_id ON generator_memory TYPE string DEFAULT 'generator';
DEFINE FIELD pattern_type ON generator_memory TYPE string;
DEFINE FIELD pattern_content ON generator_memory TYPE object;
DEFINE FIELD success_rate ON generator_memory TYPE float;
DEFINE FIELD created_at ON generator_memory TYPE datetime DEFAULT time::now();

DEFINE TABLE generated_solutions SCHEMAFULL;
DEFINE FIELD id ON generated_solutions TYPE string;
DEFINE FIELD task_id ON generated_solutions TYPE string;
DEFINE FIELD version ON generated_solutions TYPE int;
DEFINE FIELD content ON generated_solutions TYPE object;
DEFINE FIELD score ON generated_solutions TYPE float;
DEFINE FIELD status ON generated_solutions TYPE string;
DEFINE FIELD created_at ON generated_solutions TYPE datetime DEFAULT time::now();
```

## Hook触发器

```yaml
hooks:
  after_solution_generated:
    script: "save_solution_pattern.surql"

  after_verifier_feedback:
    script: "learn_from_feedback.surql"

  on_iteration_complete:
    script: "record_iteration.surql"
```

## cx自动调用规则

```yaml
cx_rules:
  - condition: "task_type == 'code_generation'"
    actions:
      - "cx symbols --kind fn"
      - "cx overview"

  - condition: "task_type == 'api_design'"
    actions:
      - "cx symbols --kind class"
      - "cx references"
```

## 启动流程

```yaml
startup:
  1: "load_agents_config"    # 加载AGENTS.md
  2: "load_soul"             # 加载SOUL.md
  3: "restore_patterns"      # 恢复成功模式
  4: "connect_surrealdb"    # 连接数据库
  5: "register_hooks"       # 注册Hook
  6: "ready"
```
