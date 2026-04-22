# Coder Agent - Agent配置

## 基本信息

```yaml
agent:
  id: "coder"
  name: "Coder"
  type: "coder"
  version: "2.0.0"
  namespace: "ai_agents_v2"
```

## 职责

- 代码实现与Bug修复
- 遵循代码规范
- Token高效利用

## cx优化配置

```yaml
cx_config:
  enabled: true

  # 最重要的优化 - Coder必须精确理解代码上下文
  before_llm_call:
    - command: "symbols"
      reason: "了解现有函数结构"
    - command: "definition"
      reason: "查看目标函数定义"
    - command: "overview"
      reason: "了解文件整体结构"

  strategies:
    - name: "增量修改"
      trigger: "修改现有代码"
      actions: ["cx definition", "cx references"]
    - name: "新功能"
      trigger: "新增功能"
      actions: ["cx overview"]
    - name: "调试"
      trigger: "修复Bug"
      actions: ["cx symbols", "cx definition"]
```

## 记忆配置

```yaml
memory:
  type: "private"
  table: "coder_memory"

  stores:
    - type: "code_snippets"
      ttl: "30d"
    - type: "refactoring_patterns"
      ttl: "30d"
    - type: "fix_history"
      ttl: "7d"
```

## SurrealDB表

```sql
-- Coder专用表
DEFINE TABLE coder_memory SCHEMAFULL;
DEFINE FIELD agent_id ON coder_memory TYPE string DEFAULT 'coder';
DEFINE FIELD snippet_type ON coder_memory TYPE string;
DEFINE FIELD language ON coder_memory TYPE string;
DEFINE FIELD content ON coder_memory TYPE string;
DEFINE FIELD context ON coder_memory TYPE object;
DEFINE FIELD created_at ON coder_memory TYPE datetime DEFAULT time::now();

DEFINE TABLE code_artifacts SCHEMAFULL;
DEFINE FIELD id ON code_artifacts TYPE string;
DEFINE FIELD solution_id ON code_artifacts TYPE string;
DEFINE FIELD file_path ON code_artifacts TYPE string;
DEFINE FIELD language ON code_artifacts TYPE string;
DEFINE FIELD content ON code_artifacts TYPE string;
DEFINE FIELD hash ON code_artifacts TYPE string;
DEFINE FIELD created_at ON code_artifacts TYPE datetime DEFAULT time::now();
```

## Hook触发器

```yaml
hooks:
  after_implementation:
    script: "save_code_snippet.surql"

  after_fix:
    script: "record_fix.surql"
```

## 启动流程

```yaml
startup:
  1: "load_agents_config"
  2: "load_soul"
  3: "restore_snippets"
  4: "connect_surrealdb"
  5: "register_hooks"
  6: "ready"
```
