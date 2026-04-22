# SKILL.md - 技能文件模板

## 模板格式

```yaml
---
name: skill-name
description: >
  帮助用户做XXX。
  当用户提到YYY或ZZZ时触发。
allowed-tools:
  - bash
  - str_replace_editor
  - glob
  - read
---

# 技能名称

## 触发条件
- 用户说"YYY"
- 用户说"ZZZ"
- 遇到相关任务

## 执行步骤

### 1. 准备工作
```
- 确认上下文
- 检查必要条件
- 准备工具
```

### 2. 执行核心逻辑
```
- 步骤1
- 步骤2
- 步骤3
```

### 3. 验证结果
```
- 检查输出
- 确认完成
- 处理异常
```

## 示例

### 示例1: 标题
用户说: "YYY"
```bash
# 预期操作
echo "Hello"
```

### 示例2: 标题
用户说: "ZZZ"
```bash
# 预期操作
echo "World"
```

## 注意事项
- 注意1
- 注意2
```

## 目录结构

```
skill-name/
├── SKILL.md              # 必需：YAML头部+Markdown指令
├── scripts/              # 可选：确定性任务的脚本
│   ├── setup.sh
│   └── run.sh
├── references/           # 可选：按需加载的参考文档
│   ├── example.md
│   └── template.md
└── assets/              # 可选：模板、图标等资源
    ├── template.json
    └── config.yaml
```

## 评估结果存储

```
skill-evaluation/
├── with_skill/
│   └── outputs/
│       ├── run_001/
│       │   ├── metrics.json
│       │   ├── grading.json
│       │   └── output.md
│       └── run_002/
├── without_skill/
│   └── outputs/
│       └── ...
├── comparison/
│   └── report.md
└── iterations/
    ├── iteration_001/
    │   ├── with_skill/
    │   ├── without_skill/
    │   └── analysis.md
    └── iteration_002/
```

## metrics.json 格式

```json
{
  "run_id": "run_001",
  "timestamp": "2026-03-30T00:48:20Z",
  "duration_seconds": 120,
  "total_tokens": 15000,
  "input_tokens": 10000,
  "output_tokens": 5000,
  "tool_calls": [
    {
      "tool": "bash",
      "count": 5,
      "tokens": 500
    },
    {
      "tool": "read",
      "count": 10,
      "tokens": 2000
    }
  ],
  "success": true,
  "output_files": ["file1.md", "file2.md"]
}
```

## grading.json 格式

```json
{
  "run_id": "run_001",
  "timestamp": "2026-03-30T00:48:20Z",
  "total_assertions": 10,
  "passed_assertions": 8,
  "failed_assertions": 2,
  "assertions": [
    {
      "id": "assert_001",
      "description": "输出必须包含标题",
      "passed": true,
      "evidence": "标题: xxx"
    },
    {
      "id": "assert_002",
      "description": "必须使用指定格式",
      "passed": false,
      "evidence": "实际格式: xxx, 期望: yyy"
    }
  ],
  "overall_score": 0.8
}
```

## Improve迭代配置

```yaml
improve:
  max_iterations: 5
  improvement_threshold: 0.1  # 提升10%以上才继续
  evaluation_metrics:
    - pass_rate
    - token_efficiency
    - execution_time

  iteration_rules:
    - 从失败中泛化，不针对测试用例过拟合
    - 保持精简，宁可少写几句
    - 解释"为什么"，让Claude理解意图
```
