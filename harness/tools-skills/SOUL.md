# Tools & Skills - 工具与技能管理

## 组件定义

Tools & Skills是Hermes Engineering的核心组件之一，负责扩展Agent的行动能力。它通过提供标准化的工具接口和可组合的技能库，让Agent能够执行复杂的操作任务。

## 核心职责

### 1. 工具注册与管理

- **工具注册表**: 维护所有可用工具的元数据
- **版本控制**: 管理工具的不同版本
- **依赖解析**: 处理工具间的依赖关系
- **生命周期**: 管理工具的安装、更新、卸载

### 2. 技能库管理

- **技能定义**: 标准的技能文件格式(SKILL.md)
- **技能组合**: 将多个工具组合成复杂技能
- **技能评分**: 评估技能的质量和适用性
- **技能发现**: 基于上下文智能推荐技能

### 3. 调用优化

- **参数验证**: 确保传入参数的合法性
- **重试机制**: 处理临时性失败
- **超时控制**: 防止工具长时间阻塞
- **结果缓存**: 避免重复调用

## SurrealDB工具模型

```sql
-- 工具注册表
DEFINE TABLE tools SCHEMAFULL;
DEFINE FIELD id ON tools TYPE string;
DEFINE FIELD name ON tools TYPE string;
DEFINE FIELD version ON tools TYPE string;
DEFINE FIELD description ON tools TYPE string;
DEFINE FIELD category ON tools TYPE string;
DEFINE FIELD parameters ON tools TYPE array;
DEFINE FIELD returns ON tools TYPE object;
DEFINE FIELD examples ON tools TYPE array;
DEFINE FIELD dependencies ON tools TYPE array;
DEFINE FIELD source ON tools TYPE string;
DEFINE FIELD installed_at ON tools TYPE datetime;
DEFINE FIELD last_used ON tools TYPE datetime;
DEFINE FIELD use_count ON tools TYPE int DEFAULT 0;
DEFINE FIELD rating ON tools TYPE float DEFAULT 0.0;

-- 技能定义
DEFINE TABLE skills SCHEMAFULL;
DEFINE FIELD id ON skills TYPE string;
DEFINE FIELD name ON skills TYPE string;
DEFINE FIELD description ON skills TYPE string;
DEFINE FIELD version ON skills TYPE string;
DEFINE FIELD trigger ON skills TYPE array; -- 触发关键词
DEFINE FIELD tools ON skills TYPE array; -- 使用的工具列表
DEFINE FIELD workflow ON skills TYPE object; -- 技能工作流
DEFINE FIELD examples ON skills TYPE array;
DEFINE FIELD author ON skills TYPE string;
DEFINE FIELD tags ON skills TYPE array;
DEFINE FIELD rating ON skills TYPE float DEFAULT 0.0;
DEFINE FIELD use_count ON skills TYPE int DEFAULT 0;
DEFINE FIELD created_at ON skills TYPE datetime;
DEFINE FIELD updated_at ON skills TYPE datetime;

-- 工具调用记录
DEFINE TABLE tool_executions SCHEMAFULL;
DEFINE FIELD id ON tool_executions TYPE string;
DEFINE FIELD tool_id ON tool_executions TYPE string;
DEFINE FIELD agent_id ON tool_executions TYPE string;
DEFINE FIELD parameters ON tool_executions TYPE object;
DEFINE FIELD result ON tool_executions TYPE object;
DEFINE FIELD status ON tool_executions TYPE string; -- success, failure, timeout
DEFINE FIELD duration_ms ON tool_executions TYPE int;
DEFINE FIELD error_message ON tool_executions TYPE option<string>;
DEFINE FIELD timestamp ON tool_executions TYPE datetime;

-- 技能评分
DEFINE TABLE skill_ratings SCHEMAFULL;
DEFINE FIELD id ON skill_ratings TYPE string;
DEFINE FIELD skill_id ON skill_ratings TYPE string;
DEFINE FIELD user_id ON skill_ratings TYPE string;
DEFINE FIELD quality ON skill_ratings TYPE float; -- 1-5
DEFINE FIELD usefulness ON skill_ratings TYPE float; -- 1-5
DEFINE FIELD feedback ON skill_ratings TYPE option<string>;
DEFINE FIELD timestamp ON skill_ratings TYPE datetime;

-- 索引
DEFINE INDEX idx_tool_category ON tools FIELDS category;
DEFINE INDEX idx_skill_trigger ON skills FIELDS trigger;
DEFINE INDEX idx_execution_tool ON tool_executions FIELDS tool_id, timestamp;
```

## 技能文件格式 (SKILL.md)

```yaml
---
name: api-doc-generator
description: >
  帮助用户生成API文档。当用户提到"生成API文档"、
  "API文档"、"接口文档"时触发此技能。
version: 1.0.0
author: TeamAI
tags:
  - documentation
  - api
  - openapi
trigger:
  - api文档
  - 生成文档
  - 接口说明
allowed-tools:
  - bash
  - read_file
  - write_file
dependencies:
  - swagger-cli (optional)
output-format: openapi
---

## 技能描述

此技能分析代码中的API定义，自动生成符合OpenAPI 3.0规范的文档。

## 输入要求

- API代码文件路径
- 输出文档路径(可选)

## 输出

- OpenAPI 3.0 JSON/YAML文件
- Markdown格式文档(可选)
```

## 工具分类

### 文件操作类

| 工具 | 用途 | Token优化 |
|------|------|----------|
| read_file | 读取文件 | cx overview |
| write_file | 写入文件 | - |
| edit_file | 编辑文件 | cx definition |
| glob | 文件搜索 | - |

### 代码分析类

| 工具 | 用途 | Token优化 |
|------|------|----------|
| cx overview | 文件结构 | ~200 token |
| cx definition | 定义查看 | ~200 token |
| cx symbols | 符号列表 | ~70 token |
| cx references | 引用追踪 | 极少 |

### 系统操作类

| 工具 | 用途 |
|------|------|
| bash | 执行命令 |
| deploy | 部署服务 |
| apt_install | 安装包 |

### 网络操作类

| 工具 | 用途 |
|------|------|
| mcp__matrix__batch_web_search | 网页搜索 |
| extract_content_from_websites | 内容提取 |
| mcp__matrix__flights_search | 航班搜索 |

## 技能组合示例

```yaml
# 复杂技能: 端到端代码审查
comprehensive-code-review:
  description: "完整的代码审查流程"
  workflow:
    - step: 1
      name: 代码获取
      tool: read_file
    - step: 2
      name: 结构分析
      tool: cx overview
    - step: 3
      name: 安全扫描
      tool: security-scanner
    - step: 4
      name: 性能分析
      tool: performance-analyzer
    - step: 5
      name: 生成报告
      tool: report-generator
```

## 工具调用优化策略

### 1. 参数验证

```python
def validate_parameters(tool_schema, params):
    """参数验证"""
    for param in tool_schema.parameters:
        if param.required and param.name not in params:
            raise ValidationError(f"Missing required: {param.name}")
        if param.name in params:
            if not validate_type(params[param.name], param.type):
                raise TypeError(f"Invalid type for {param.name}")
```

### 2. 智能重试

```python
def execute_with_retry(tool, params, max_retries=3):
    """智能重试机制"""
    for attempt in range(max_retries):
        try:
            return tool.execute(params)
        except TransientError as e:
            if attempt == max_retries - 1:
                raise
            wait_time = backoff(attempt)
            sleep(wait_time)
```

### 3. 结果缓存

```sql
-- 缓存命中检查
SELECT * FROM tool_executions
WHERE tool_id = $tool_id
AND parameters = $params
AND status = 'success'
AND timestamp > time::now() - 1h
LIMIT 1;
```

## 技能发现算法

```sql
-- 基于上下文的技能推荐
SELECT skill.*,
    (SELECT count(*) FROM UNWRAP(skill.trigger) WHERE string::lowercase($query) CONTAINS string::lowercase) AS match_count
FROM skills skill
WHERE skill.domain = $domain
ORDER BY match_count DESC, skill.rating DESC
LIMIT 5;
```

## 质量指标

- 工具成功率
- 平均调用延迟
- 技能命中率
- 用户满意度
