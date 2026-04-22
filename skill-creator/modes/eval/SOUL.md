# Skill Creator - EVAL模式

## 模式定义

EVAL模式是Skill Creator的评估引擎，负责验证技能输出的正确性、完整性和质量。它执行测试用例并生成详细的评估报告。

## 工作流程

```
技能输出 → 测试执行 → 结果评估 → 报告生成 → 反馈输出
```

## 核心职责

### 1. 测试执行
- **用例生成**: 根据断言生成测试用例
- **环境准备**: 设置测试环境
- **执行测试**: 运行测试并收集结果
- **结果收集**: 汇总测试结果

### 2. 结果评估
- **断言验证**: 检查输出是否满足断言
- **质量评分**: 多维度质量评分
- **问题识别**: 发现问题并分类
- **趋势分析**: 分析评估历史

### 3. 报告生成
- **详细报告**: 生成结构化评估报告
- **问题清单**: 列出发现的问题
- **改进建议**: 提供改进方向
- **评分汇总**: 总体评分和维度评分

## Grader评估器

Grader是EVAL模式的核心Agent，负责判断技能输出是否满足质量标准。

### SurrealDB模型
```sql
-- 评估结果
DEFINE TABLE eval_results SCHEMAFULL;
DEFINE FIELD id ON eval_results TYPE string;
DEFINE FIELD task_id ON eval_results TYPE string;
DEFINE FIELD skill_output ON eval_results TYPE object;
DEFINE FIELD assertions ON eval_results TYPE array;
DEFINE FIELD assertion_results ON eval_results TYPE array;
DEFINE FIELD overall_score ON eval_results TYPE float;
DEFINE FIELD dimensions ON eval_results TYPE object;
DEFINE FIELD verdict ON eval_results TYPE string;
DEFINE FIELD executed_at ON eval_results TYPE datetime;

-- 断言定义
DEFINE TABLE assertions SCHEMAFULL;
DEFINE FIELD id ON assertions TYPE string;
DEFINE FIELD name ON eval_results TYPE string;
DEFINE FIELD type ON assertions TYPE string; -- eq, contains, regex, custom
DEFINE FIELD expected ON assertions TYPE object;
DEFINE FIELD weight ON assertions TYPE float DEFAULT 1.0;
```

### 评估维度

| 维度 | 权重 | 说明 |
|------|------|------|
| 正确性 | 0.4 | 输出是否正确 |
| 完整性 | 0.3 | 是否覆盖所有需求 |
| 效率 | 0.2 | 执行效率 |
| 可维护性 | 0.1 | 代码质量 |

### 执行流程
```python
class SkillGrader:
    async def evaluate(self, skill_output, assertions):
        results = []

        for assertion in assertions:
            result = await self.check_assertion(
                assertion,
                skill_output
            )
            results.append(result)

        # 计算维度分数
        dimensions = self.calculate_dimensions(results)

        # 生成判定
        verdict = self.generate_verdict(dimensions)

        return {
            "assertion_results": results,
            "dimensions": dimensions,
            "overall_score": self.weighted_score(dimensions),
            "verdict": verdict
        }
```

### 断言类型

```python
# 相等断言
{"type": "eq", "field": "status", "expected": 200}

# 包含断言
{"type": "contains", "field": "content", "expected": "success"}

# 正则断言
{"type": "regex", "field": "output", "pattern": r"^Task.*completed$"}

# 范围断言
{"type": "range", "field": "duration_ms", "min": 0, "max": 5000}

# 自定义断言
{"type": "custom", "function": "validate_schema"}
```

### 评估报告格式

```json
{
  "eval_id": "eval_xxx",
  "timestamp": "2026-03-31T00:15:00Z",
  "verdict": "PASS",
  "overall_score": 0.87,
  "dimensions": {
    "correctness": {
      "score": 0.92,
      "details": {
        "assertions_passed": 8,
        "assertions_failed": 1
      }
    },
    "completeness": {
      "score": 0.85,
      "details": {
        "coverage": 0.9,
        "gaps": ["error_handling"]
      }
    },
    "efficiency": {
      "score": 0.80,
      "details": {
        "duration_ms": 2500,
        "token_count": 1500
      }
    }
  },
  "assertions": [
    {
      "name": "output_format",
      "status": "PASS",
      "actual": "json",
      "expected": "json"
    },
    {
      "name": "response_time",
      "status": "PASS",
      "actual": 150,
      "expected": "< 500"
    }
  ],
  "issues": [
    {
      "severity": "MEDIUM",
      "description": "未处理空输入情况",
      "location": "line 42"
    }
  ],
  "recommendations": [
    "增加空值检查",
    "优化错误处理逻辑"
  ]
}
```

## 集成方式

### 与Generator集成
```python
async def generate_with_eval(task):
    # 生成方案
    solution = await generator.create(task)

    # 评估方案
    eval_result = await grader.evaluate(
        solution,
        get_assertions(task)
    )

    if eval_result.verdict == "FAIL":
        # 返回问题让Generator修复
        return {
            "status": "needs_fix",
            "issues": eval_result.issues
        }

    return {
        "status": "approved",
        "score": eval_result.overall_score
    }
```

### 与Commander集成
```python
async def coordinate_with_gate(task):
    # 协调执行
    result = await commander.execute(task)

    # 质量门禁检查
    gate_result = await grader.evaluate_gate(result)

    if not gate_result.passed:
        # 触发回滚或人工介入
        await commander.rollback()
        notify_human("Quality gate failed")

    return result
```

## 评分阈值

| 评分范围 | 判定 | 行动 |
|---------|------|------|
| >= 0.95 | EXCELLENT | 直接通过 |
| >= 0.85 | PASS | 通过 |
| >= 0.70 | CONDITIONAL | 有限通过 |
| >= 0.50 | FAIL | 需要修复 |
| < 0.50 | REJECT | 拒绝 |

## 反馈机制

### 实时反馈
```python
async def stream_feedback(self, task_id):
    """流式反馈评估进度"""
    async for progress in self.evaluate_stream(task_id):
        yield {
            "stage": progress.stage,
            "completed": progress.total,
            "current_assertion": progress.current
        }
```

### 改进建议
```python
def generate_suggestions(self, eval_result):
    """生成改进建议"""
    suggestions = []

    if eval_result.dimensions.correctness < 0.8:
        suggestions.append({
            "priority": "high",
            "action": "修复断言失败的问题"
        })

    if eval_result.dimensions.completeness < 0.8:
        suggestions.append({
            "priority": "medium",
            "action": "补充缺失的功能点"
        })

    return suggestions
```
