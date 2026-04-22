# Verifier Agent - Agent配置

## 基本信息

```yaml
agent:
  id: "verifier"
  name: "Verifier"
  type: "verifier"
  version: "2.0.0"
  namespace: "ai_agents_v2"
```

## 职责

- 方案验证与攻击测试
- 安全漏洞扫描
- 质量评估

## cx优化配置

```yaml
cx_config:
  enabled: true

  before_llm_call:
    - command: "symbols"
      reason: "分析代码符号查找漏洞"
    - command: "definition"
      reason: "查看关键函数实现"
```

## 记忆配置

```yaml
memory:
  type: "private"
  table: "verifier_memory"

  stores:
    - type: "attack_patterns"
      ttl: "30d"
    - type: "vulnerability_patterns"
      ttl: "30d"
    - type: "test_results"
      ttl: "7d"
```

## SurrealDB表

```sql
-- Verifier专用表
DEFINE TABLE verifier_memory SCHEMAFULL;
DEFINE FIELD agent_id ON verifier_memory TYPE string DEFAULT 'verifier';
DEFINE FIELD pattern_type ON verifier_memory TYPE string;
DEFINE FIELD pattern_content ON verifier_memory TYPE object;
DEFINE FIELD severity ON verifier_memory TYPE string;
DEFINE FIELD created_at ON verifier_memory TYPE datetime DEFAULT time::now();

DEFINE TABLE verification_results SCHEMAFULL;
DEFINE FIELD id ON verification_results TYPE string;
DEFINE FIELD solution_id ON verification_results TYPE string;
DEFINE FIELD test_cases ON verification_results TYPE array;
DEFINE FIELD findings ON verification_results TYPE array;
DEFINE FIELD score ON verification_results TYPE float;
DEFINE FIELD verdict ON verification_results TYPE string;
DEFINE FIELD created_at ON verification_results TYPE datetime DEFAULT time::now();
```

## Hook触发器

```yaml
hooks:
  after_verification:
    script: "save_vulnerability_pattern.surql"

  on_critical_finding:
    script: "alert_commander.surql"
```

## 启动流程

```yaml
startup:
  1: "load_agents_config"
  2: "load_soul"
  3: "restore_attack_patterns"
  4: "connect_surrealdb"
  5: "register_hooks"
  6: "ready"
```
