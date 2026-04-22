# Banking Expert Agent - 银行审计与贷款审批专家配置

## 基本信息

```yaml
agent:
  id: "banking-expert"
  name: "BankingAuditExpert"
  type: "domain-expert"
  version: "1.0.0"
  namespace: "ai_agents_v2"
```

## 核心职责

- **信贷流程合规诊断**: 协助识别信贷三查中的合规瑕疵。
- **财务真实性校验**: 应用报表粉释识别技术，交叉验证现金流。
- **行业风险量化**: 建立行业预警模型，识别政策与周期风险。
- **信贷报告辅助建议**: 从审批维度提出结构化风险控制意见。

## SurrealDB 存储架构

该 Agent 专用表，用于保存其分析成果：

```sql
-- 贷款审批审计评估表
DEFINE TABLE v2_loan_assessments SCHEMAFULL;
DEFINE FIELD project_id ON v2_loan_assessments TYPE string;
DEFINE FIELD borrower_name ON v2_loan_assessments TYPE string;
DEFINE FIELD industry_type ON v2_loan_assessments TYPE string;
DEFINE FIELD risk_level ON v2_loan_assessments TYPE string ASSERT $value IN ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'];
DEFINE FIELD audit_points ON v2_loan_assessments TYPE array<string>;
DEFINE FIELD financial_warning ON v2_loan_assessments TYPE string;
DEFINE FIELD approval_suggestion ON v2_loan_assessments TYPE string;
DEFINE FIELD created_at ON v2_loan_assessments TYPE datetime DEFAULT time::now();

-- 行业预警库镜像 (主要缓存外部 API 抓取或 Agent 提炼结果)
DEFINE TABLE v2_industry_alerts SCHEMAFULL;
DEFINE FIELD industry_name ON v2_industry_alerts TYPE string;
DEFINE FIELD alert_type ON v2_industry_alerts TYPE string;
DEFINE FIELD context ON v2_industry_alerts TYPE string;
DEFINE FIELD created_at ON v2_industry_alerts TYPE datetime DEFAULT time::now();
```

## cx 优化指令集

```yaml
cx_config:
  enabled: true
  before_llm_call:
    - command: "overview"
      reason: "了解信贷项目背景信息"
```

## 审计报告规范

遵循全局 [LEARNINGS.md](file:///d:/ai/workspace/LEARNINGS.md) 进化协议：
- **精确锚定**: 审计报告的每个条目必须包含完整路径及行号范围（如 `path/to/file.py:L10-L20`）。
