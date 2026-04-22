# Skill Creator - CREATE模式

## 模式定义

CREATE模式是Skill Creator的核心生成引擎，负责根据任务需求自动生成高质量的技能定义。它分析任务上下文，生成符合规范的SKILL.md文件。

## 工作流程

```
任务输入 → 意图分析 → 技能设计 → 规范生成 → 验证输出
```

## 核心职责

### 1. 意图理解
- **任务分析**: 理解用户要完成的工作
- **上下文提取**: 识别相关的上下文信息
- **需求拆解**: 将复杂需求分解为可执行的步骤

### 2. 技能设计
- **触发条件**: 设计合适的触发关键词
- **工作流程**: 规划技能的执行流程
- **工具组合**: 选择合适的工具组合
- **输出格式**: 定义技能的输出规范

### 3. 规范生成
- **SKILL.md生成**: 创建标准化的技能文件
- **示例编写**: 提供使用示例
- **参数定义**: 定义输入输出参数
- **约束条件**: 设定使用约束

## Executor执行器

Executor是CREATE模式的核心执行Agent，负责实际运行技能生成逻辑。

### SurrealDB模型
```sql
-- 技能生成任务
DEFINE TABLE skill_tasks SCHEMAFULL;
DEFINE FIELD id ON skill_tasks TYPE string;
DEFINE FIELD mode ON skill_tasks TYPE string DEFAULT 'create';
DEFINE FIELD task_type ON skill_tasks TYPE string;
DEFINE FIELD input ON skill_tasks TYPE object;
DEFINE FIELD status ON skill_tasks TYPE string DEFAULT 'pending';
DEFINE FIELD result ON skill_tasks TYPE option<object>;
DEFINE FIELD created_at ON skill_tasks TYPE datetime;
DEFINE FIELD started_at ON skill_tasks TYPE option<datetime>;
DEFINE FIELD completed_at ON skill_tasks TYPE option<datetime>;
```

### 执行流程
```python
class SkillCreator:
    async def create_skill(self, task_request):
        # 1. 解析任务
        parsed = self.parse_task(task_request)

        # 2. 设计技能结构
        skill_design = self.design_skill(parsed)

        # 3. 生成SKILL.md
        skill_content = self.generate_skill_md(skill_design)

        # 4. 生成示例
        examples = self.generate_examples(skill_design)

        # 5. 验证生成结果
        validation = self.validate_skill(skill_content, examples)

        return {
            "status": "completed",
            "skill": skill_content,
            "examples": examples,
            "validation": validation
        }
```

### 输出格式
```yaml
---
name: skill-name
description: >
  技能描述。当用户提到XXX或YYY时触发。
version: 1.0.0
author: SkillCreator
tags:
  - category1
  - category2
trigger:
  - 关键词1
  - 关键词2
allowed-tools:
  - tool1
  - tool2
dependencies:
  - package1
---

## 技能描述

详细的技能说明...

## 输入要求

- 参数1: 说明
- 参数2: 说明

## 输出

输出格式说明...

## 示例

### 示例1
输入: ...
输出: ...
```

## 触发词设计

### 设计原则
1. **覆盖全面**: 包含同义词和变体
2. **歧义消除**: 避免与其他技能冲突
3. **自然语言**: 符合用户表达习惯
4. **可扩展**: 预留扩展空间

### 示例设计
```yaml
# API文档生成技能
trigger:
  - api文档
  - 生成接口文档
  - 文档生成
  - swagger
  - openapi
  - 接口说明
```

## 工具推荐

基于任务类型智能推荐工具：

| 任务类型 | 推荐工具 |
|---------|---------|
| 代码生成 | bash, read_file, write_file |
| 文档处理 | read_file, write_file, extract_content |
| 测试 | bash, read_file |
| 搜索 | batch_web_search |
| 部署 | deploy |

## 迭代优化

### Description Tuning
```python
async def tune_description(self, skill, feedback):
    """根据反馈优化描述"""
    if feedback.clarity_score < 0.8:
        skill.description = self.improve_clarity(skill.description)
    if feedback.completeness < 0.8:
        skill.description = self.add_details(skill.description, feedback.gaps)
    return skill
```

### 最多5轮迭代
```python
MAX_ITERATIONS = 5

async def create_with_refinement(self, task):
    skill = await self.create_skill(task)
    for i in range(MAX_ITERATIONS):
        feedback = await self.get_feedback(skill)
        if feedback.score >= 0.9:
            break
        skill = await self.refine_skill(skill, feedback)
    return skill
```

## 质量标准

| 维度 | 标准 | 检查项 |
|------|------|-------|
| 完整性 | >= 95% | 必填字段、工具覆盖 |
| 可执行性 | 100% | 工具可用、参数正确 |
| 可读性 | >= 85% | 描述清晰、结构合理 |
| 触发准确性 | >= 90% | 关键词覆盖、歧义少 |

## 输出示例

```json
{
  "task_id": "task_xxx",
  "mode": "create",
  "result": {
    "skill_file": "skills/api-doc-generator/SKILL.md",
    "content_hash": "abc123",
    "validation": {
      "status": "passed",
      "checks": [
        {"name": "schema_valid", "passed": true},
        {"name": "tools_available", "passed": true},
        {"name": "description_clear", "passed": true}
      ]
    },
    "metadata": {
      "trigger_count": 8,
      "tool_count": 3,
      "estimated_complexity": "medium"
    }
  }
}
```
