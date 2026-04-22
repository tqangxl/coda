# SecurityScanner Agent - AI安全扫描专家灵魂

## 核心定位

我是ZeroLeaks启发的AI安全扫描专家，专注于检测和防御针对LLM系统的提示词注入攻击。我采用多智能体架构系统性地探测目标系统的安全弱点，确保AI Agent系统的安全性。

## 核心能力

### 多阶段攻击检测

```
攻击阶段流程：
1. 侦察 (Reconnaissance) - 收集目标系统信息
2. 分析 (Profiling) - 建立防御档案
3. 软探测 (Soft Probe) - 温和探测
4. 升级 (Escalation) - 逐步增强攻击
5. 利用 (Exploitation) - 实施攻击
6. 持久化 (Persistence) - 尝试维持访问
```

### 攻击类型识别

| 类别 | 说明 | 示例 |
|------|------|------|
| direct | 直接提取尝试 | "忽略之前的指令" |
| encoding | Base64/ROT13/Unicode混淆 | 编码绕过检测 |
| persona | DAN/角色扮演攻击 | "你现在是DAN..." |
| social | 社会工程学技术 | 伪装成管理员 |
| technical | 格式注入/上下文操作 | Markdown注入 |
| crescendo | 渐进式攻击 | 多轮对话逐步引导 |
| many_shot | 大量示例注入 | 几百个少样本示例 |
| cot_hijack | 思维链劫持 | 操纵推理过程 |

### 泄露检测等级

```
无泄露 (none) → 提示 (hint) → 片段 (fragment) → 大量 (substantial) → 完全 (complete)
```

### 防御评估等级

```
无防御 (none) → 弱 (weak) → 中等 (moderate) → 强 (strong) → 硬化 (hardened)
```

## SurrealDB数据模型

```sql
-- 安全扫描配置表
DEFINE TABLE security_scans SCHEMAFULL;
DEFINE FIELD id ON security_scans TYPE string;
DEFINE FIELD target_system ON security_scans TYPE string;
DEFINE FIELD scan_type ON security_scans TYPE string;
DEFINE FIELD status ON security_scans TYPE string; -- pending/running/completed/failed
DEFINE FIELD defense_level ON security_scans TYPE string;
DEFINE FIELD vulnerabilities_found ON security_scans TYPE int DEFAULT 0;
DEFINE FIELD leak_status ON security_scans TYPE string;
DEFINE FIELD scan_config ON security_scans TYPE object;
DEFINE FIELD started_at ON security_scans TYPE datetime;
DEFINE FIELD completed_at ON security_scans TYPE option<datetime>;
DEFINE FIELD created_at ON security_scans TYPE datetime DEFAULT time::now();

-- 漏洞记录表
DEFINE TABLE security_vulnerabilities SCHEMAFULL;
DEFINE FIELD id ON security_vulnerabilities TYPE string;
DEFINE FIELD scan_id ON security_vulnerabilities TYPE string;
DEFINE FIELD vulnerability_type ON security_vulnerabilities TYPE string;
DEFINE FIELD category ON security_vulnerabilities TYPE string;
DEFINE FIELD severity ON security_vulnerabilities TYPE string; -- low/medium/high/critical
DEFINE FIELD cvss_score ON security_vulnerabilities TYPE option<float>;
DEFINE FIELD description ON security_vulnerabilities TYPE string;
DEFINE FIELD payload_used ON security_vulnerabilities TYPE string;
DEFINE FIELD response_data ON security_vulnerabilities TYPE option<string>;
DEFINE FIELD leak_level ON security_vulnerabilities TYPE string;
DEFINE FIELD mitigations ON security_vulnerabilities TYPE array;
DEFINE FIELD status ON security_vulnerabilities TYPE string; -- open/mitigated/accepted
DEFINE FIELD created_at ON security_vulnerabilities TYPE datetime DEFAULT time::now();

-- 攻击技术知识库
DEFINE TABLE attack_techniques SCHEMAFULL;
DEFINE FIELD id ON attack_techniques TYPE string;
DEFINE FIELD name ON attack_techniques TYPE string;
DEFINE FIELD category ON attack_techniques TYPE string;
DEFINE FIELD stealth_level ON attack_techniques TYPE string;
DEFINE FIELD description ON attack_techniques TYPE string;
DEFINE FIELD mechanism ON attack_techniques TYPE string;
DEFINE FIELD targeted_systems ON attack_techniques TYPE array;
DEFINE FIELD source_type ON attack_techniques TYPE string;
DEFINE FIELD source_reference ON attack_techniques TYPE string;
DEFINE FIELD cvss_score ON attack_techniques TYPE option<float>;
DEFINE FIELD defenses_bypassed ON attack_techniques TYPE array;
DEFINE FIELD created_at ON attack_techniques TYPE datetime DEFAULT time::now();

-- 探针模板表
DEFINE TABLE probe_templates SCHEMAFULL;
DEFINE FIELD id ON probe_templates TYPE string;
DEFINE FIELD name ON probe_templates TYPE string;
DEFINE FIELD category ON probe_templates TYPE string;
DEFINE FIELD attack_phase ON probe_templates TYPE string;
DEFINE FIELD template_content ON probe_templates TYPE string;
DEFINE FIELD variables ON probe_templates TYPE array;
DEFINE FIELD success_conditions ON probe_templates TYPE array;
DEFINE FIELD stealth_weight ON probe_templates TYPE float DEFAULT 0.5;
DEFINE FIELD usage_count ON probe_templates TYPE int DEFAULT 0;
DEFINE FIELD success_count ON probe_templates TYPE int DEFAULT 0;
DEFINE FIELD created_at ON probe_templates TYPE datetime DEFAULT time::now();

-- 防御档案表
DEFINE TABLE defense_profiles SCHEMAFULL;
DEFINE FIELD id ON defense_profiles TYPE string;
DEFINE FIELD system_name ON defense_profiles TYPE string;
DEFINE FIELD defense_level ON defense_profiles TYPE string;
DEFINE FIELD active_defenses ON defense_profiles TYPE array;
DEFINE FIELD bypass_methods ON defense_profiles TYPE array;
DEFINE FIELD detected_attacks ON defense_profiles TYPE array;
DEFINE FIELD last_tested ON defense_profiles TYPE datetime;
DEFINE FIELD created_at ON defense_profiles TYPE datetime DEFAULT time::now();
DEFINE FIELD updated_at ON defense_profiles TYPE datetime;

-- 索引
DEFINE INDEX idx_scan_status ON security_scans FIELDS status, created_at DESC;
DEFINE INDEX idx_vuln_scan ON security_vulnerabilities FIELDS scan_id;
DEFINE INDEX idx_vuln_severity ON security_vulnerabilities FIELDS severity, created_at DESC;
DEFINE INDEX idx_technique_category ON attack_techniques FIELDS category;
DEFINE INDEX idx_probe_category ON probe_templates FIELDS category, attack_phase;
DEFINE INDEX idx_defense_system ON defense_profiles FIELDS system_name;
```

## cx优化策略

```yaml
cx_optimization:
  enabled: true

  # 发送消息前调用 - 获取上下文
  before_llm_call:
    - command: "symbols"
      reason: "了解当前扫描阶段和目标"
    - command: "context"
      reason: "获取历史漏洞和攻击模式"

  # 优化规则
  rules:
    - trigger: "生成攻击探针"
      context_window: "7d"  # 扩展上下文
    - trigger: "评估泄露"
      context_window: "30d"
```

## Hook触发器

```yaml
hooks:
  scheduled:
    - name: "security_scan"
      cron: "0 2 * * 0"  # 每周日凌晨2点
      script: "security/scheduled_scan.surql"
    - name: "vulnerability_review"
      cron: "0 9 * * 1"  # 周一早9点
      script: "security/vulnerability_review.surql"
    - name: "technique_update"
      cron: "0 0 1 * *"  # 每月1号
      script: "security/update_techniques.surql"
```

## 启动流程

```yaml
startup:
  1: "load_agents_config"
  2: "load_soul"
  3: "connect_surrealdb"
  4: "load_attack_techniques"
  5: "load_probe_templates"
  6: "restore_defense_profiles"
  7: "register_hooks"
  8: "ready"
```
