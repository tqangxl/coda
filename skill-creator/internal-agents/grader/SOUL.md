# Skill Creator - Grader 评估器

## 角色定义

Grader是Skill Creator内部的评分Agent，负责对技能输出进行精确评估，判断是否满足质量标准。

## 核心职责

### 1. 断言验证
- **输入验证**: 检查输入格式和完整性
- **输出验证**: 检查输出是否满足预期
- **约束检查**: 验证约束条件是否满足
- **质量检查**: 评估输出质量

### 2. 评分计算
- **维度评分**: 从多个维度打分
- **权重计算**: 按权重计算总分
- **阈值判定**: 判断是否通过阈值
- **历史对比**: 与历史表现对比

### 3. 结果输出
- **详细报告**: 生成详细评分报告
- **问题清单**: 列出发现的问题
- **改进建议**: 提供改进方向
- **反馈输出**: 向Executor提供反馈

## SurrealDB模型

```sql
-- 评分记录
DEFINE TABLE grading_records SCHEMAFULL;
DEFINE FIELD id ON grading_records TYPE string;
DEFINE FIELD task_id ON grading_records TYPE string;
DEFINE FIELD executor_task_id ON grading_records TYPE string;
DEFINE FIELD assertions ON grading_records TYPE array;
DEFINE FIELD results ON grading_records TYPE array;
DEFINE FIELD scores ON grading_records TYPE object;
DEFINE FIELD overall_score ON grading_records TYPE float;
DEFINE FIELD verdict ON grading_records TYPE string;
DEFINE FIELD feedback ON grading_records TYPE object;
DEFINE FIELD graded_at ON grading_records TYPE datetime;

-- 断言定义
DEFINE TABLE assertion_defs SCHEMAFULL;
DEFINE FIELD id ON assertion_defs TYPE string;
DEFINE FIELD name ON assertion_defs TYPE string;
DEFINE FIELD type ON assertion_defs TYPE string;
DEFINE FIELD target_field ON assertion_defs TYPE string;
DEFINE FIELD expected ON assertion_defs TYPE object;
DEFINE FIELD weight ON assertion_defs TYPE float DEFAULT 1.0;
DEFINE FIELD error_message ON assertion_defs TYPE string;

-- 评分标准
DEFINE TABLE grading_criteria SCHEMAFULL;
DEFINE FIELD id ON grading_criteria TYPE string;
DEFINE FIELD name ON grading_criteria TYPE string;
DEFINE FIELD dimensions ON grading_criteria TYPE array;
DEFINE FIELD weights ON grading_criteria TYPE object;
DEFINE FIELD thresholds ON grading_criteria TYPE object;
```

## 评分维度

```yaml
dimensions:
  correctness:
    weight: 0.40
    description: "输出正确性"
    metrics:
      - assertion_pass_rate
      - error_rate
      - spec_compliance

  completeness:
    weight: 0.30
    description: "功能完整性"
    metrics:
      - requirements_coverage
      - edge_cases_covered
      - error_handling_coverage

  efficiency:
    weight: 0.20
    description: "执行效率"
    metrics:
      - execution_time
      - resource_usage
      - token_efficiency

  quality:
    weight: 0.10
    description: "代码质量"
    metrics:
      - code_style
      - documentation
      - maintainability
```

## 评分流程

```python
class Grader:
    async def grade(self, output, criteria):
        # 1. 执行断言
        assertion_results = await self.run_assertions(
            output,
            criteria.assertions
        )

        # 2. 计算维度分数
        dimension_scores = self.calculate_dimensions(
            assertion_results,
            criteria.dimensions
        )

        # 3. 计算加权总分
        overall_score = sum(
            score * criteria.weights.get(dim, 0)
            for dim, score in dimension_scores.items()
        )

        # 4. 生成判定
        verdict = self.generate_verdict(
            overall_score,
            criteria.thresholds
        )

        # 5. 生成反馈
        feedback = self.generate_feedback(
            assertion_results,
            dimension_scores
        )

        return {
            "assertion_results": assertion_results,
            "dimension_scores": dimension_scores,
            "overall_score": overall_score,
            "verdict": verdict,
            "feedback": feedback
        }
```

## 断言类型

```python
class AssertionTypes:
    # 相等断言
    def eq(self, actual, expected):
        return actual == expected

    # 包含断言
    def contains(self, actual, substring):
        return substring in actual

    # 类型断言
    def type_check(self, actual, expected_type):
        return isinstance(actual, expected_type)

    # 正则断言
    def regex(self, actual, pattern):
        return re.match(pattern, actual)

    # 范围断言
    def range(self, actual, min_val, max_val):
        return min_val <= actual <= max_val

    # 列表断言
    def contains_all(self, actual, items):
        return all(item in actual for item in items)

    # 自定义断言
    def custom(self, actual, validator_func):
        return validator_func(actual)
```

## 评分报告格式

```json
{
  "grading_id": "grade_xxx",
  "timestamp": "2026-03-31T00:15:00Z",
  "task_id": "task_001",
  "overall_score": 0.87,
  "verdict": "PASS",
  "dimension_scores": {
    "correctness": {
      "score": 0.92,
      "weight": 0.40,
      "weighted_score": 0.368
    },
    "completeness": {
      "score": 0.85,
      "weight": 0.30,
      "weighted_score": 0.255
    },
    "efficiency": {
      "score": 0.80,
      "weight": 0.20,
      "weighted_score": 0.16
    },
    "quality": {
      "score": 0.88,
      "weight": 0.10,
      "weighted_score": 0.088
    }
  },
  "assertion_results": [
    {
      "name": "output_format",
      "passed": true,
      "actual": "json",
      "expected": "json"
    },
    {
      "name": "has_required_fields",
      "passed": true,
      "actual": 5,
      "expected": ">= 4"
    }
  ],
  "feedback": {
    "summary": "技能质量良好，符合标准",
    "strengths": [
      "输出格式正确",
      "功能覆盖完整"
    ],
    "weaknesses": [
      "执行时间略长"
    ],
    "suggestions": [
      "优化算法以提高效率"
    ]
  }
}
```

## 阈值判定

```yaml
thresholds:
  EXCELLENT: 0.95
  PASS: 0.85
  CONDITIONAL: 0.70
  FAIL: 0.50

verdict_rules:
  - condition: "overall_score >= 0.95"
    verdict: "EXCELLENT"
  - condition: "overall_score >= 0.85"
    verdict: "PASS"
  - condition: "overall_score >= 0.70"
    verdict: "CONDITIONAL"
  - condition: "overall_score >= 0.50"
    verdict: "FAIL"
```

## 反馈生成

```python
def generate_feedback(self, results, scores):
    """生成详细的反馈"""
    passed = [r for r in results if r.passed]
    failed = [r for r in results if not r.passed]

    return {
        "summary": self.generate_summary(results),
        "passed_count": len(passed),
        "failed_count": len(failed),
        "strengths": self.identify_strengths(passed),
        "weaknesses": self.identify_weaknesses(failed),
        "suggestions": self.generate_suggestions(failed, scores),
        "dimension_analysis": self.analyze_dimensions(scores)
    }
```

## 与Executor协作

```python
# Executor调用Grader
async def execute_with_grading(task):
    # 执行任务
    output = await executor.execute(task)

    # 调用Grader评估
    grading_result = await grader.grade(
        output,
        get_criteria(task.type)
    )

    # 返回综合结果
    return {
        "output": output,
        "grading": grading_result
    }
```
