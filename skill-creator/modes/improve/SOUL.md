# Skill Creator - IMPROVE模式

## 模式定义

IMPROVE模式是Skill Creator的优化引擎，负责根据评估反馈自动改进技能输出。它采用最小改动原则，在保持原有优势的同时针对性地修复问题。

## 工作流程

```
评估结果 → 问题分析 → 改动规划 → 实施改进 → 验证改进
```

## 核心职责

### 1. 问题分析
- **根因定位**: 找出问题的根本原因
- **影响评估**: 评估问题的严重程度
- **修复优先级**: 确定修复的先后顺序
- **改动范围**: 确定需要改动的最小范围

### 2. 改动规划
- **改动策略**: 制定具体的改进方案
- **风险评估**: 评估改动可能引入的风险
- **回滚计划**: 准备回滚方案
- **测试计划**: 制定改进后的测试计划

### 3. 实施改进
- **最小改动**: 只改必要的部分
- **渐进式**: 分步骤实施
- **版本记录**: 记录改动历史
- **持续验证**: 每步改进后验证

## Analyzer分析器

Analyzer是IMPROVE模式的核心Agent，负责深度分析评估结果，生成智能改进建议。

### SurrealDB模型
```sql
-- 改进任务
DEFINE TABLE improve_tasks SCHEMAFULL;
DEFINE FIELD id ON improve_tasks TYPE string;
DEFINE FIELD eval_id ON improve_tasks TYPE string;
DEFINE FIELD original_output ON improve_tasks TYPE object;
DEFINE FIELD issues ON improve_tasks TYPE array;
DEFINE FIELD improvement_plan ON improve_tasks TYPE object;
DEFINE FIELD iterations ON improve_tasks TYPE int DEFAULT 0;
DEFINE FIELD max_iterations ON improve_tasks TYPE int DEFAULT 5;
DEFINE FIELD status ON improve_tasks TYPE string DEFAULT 'analyzing';
DEFINE FIELD created_at ON improve_tasks TYPE datetime;

-- 改进历史
DEFINE TABLE improvement_history SCHEMAFULL;
DEFINE FIELD id ON improvement_history TYPE string;
DEFINE FIELD improve_task_id ON improve_tasks TYPE string;
DEFINE FIELD iteration ON improvement_history TYPE int;
DEFINE FIELD changes ON improvement_history TYPE array;
DEFINE FIELD validation_result ON improvement_history TYPE object;
DEFINE FIELD timestamp ON improve_history TYPE datetime;

-- 改动记录
DEFINE TABLE change_records SCHEMAFULL;
DEFINE FIELD id ON change_records TYPE string;
DEFINE FIELD improve_task_id ON improve_records TYPE string;
DEFINE FIELD change_type ON change_records TYPE string;
DEFINE FIELD location ON change_records TYPE string;
DEFINE FIELD before ON change_records TYPE string;
DEFINE FIELD after ON change_records TYPE string;
DEFINE FIELD rationale ON change_records TYPE string;
```

### 分析流程
```python
class ImprovementAnalyzer:
    async def analyze_and_improve(self, eval_result, original):
        # 1. 问题分类
        categorized_issues = self.categorize_issues(eval_result.issues)

        # 2. 根因分析
        root_causes = self.find_root_causes(categorized_issues)

        # 3. 生成改进方案
        plan = self.create_improvement_plan(
            root_causes,
            original
        )

        # 4. 实施改进
        improved = await self.execute_improvements(plan, original)

        # 5. 验证改进
        validated = await self.validate_improvements(
            improved,
            eval_result
        )

        return {
            "original_issues": eval_result.issues,
            "improvements_made": plan.changes,
            "result": validated,
            "iterations": plan.iterations
        }
```

### 问题分类

```python
ISSUE_CATEGORIES = {
    "syntax": {
        "severity": "high",
        "fix_strategy": "auto_fix",
        "examples": ["括号不匹配", "缺少分号"]
    },
    "logic": {
        "severity": "critical",
        "fix_strategy": "analyze_and_fix",
        "examples": ["条件判断错误", "循环逻辑问题"]
    },
    "completeness": {
        "severity": "medium",
        "fix_strategy": "enhance",
        "examples": ["缺少错误处理", "未处理边界情况"]
    },
    "quality": {
        "severity": "low",
        "fix_strategy": "refine",
        "examples": ["命名不规范", "注释不清晰"]
    },
    "performance": {
        "severity": "medium",
        "fix_strategy": "optimize",
        "examples": ["重复计算", "内存泄漏"]
    }
}
```

### 改动策略

#### 1. 自动修复 (Auto-Fix)
```python
# 可自动修复的问题
SYNTAX_PATTERNS = {
    r"\{\s*\}": "{}",  # 清理多余空格
    r"\n\n\n": "\n\n",  # 清理多余空行
    r"//\s*$": "",  # 清理行尾注释
}
```

#### 2. 分析修复 (Analyze-Fix)
```python
async def fix_logic_issues(self, issues):
    """修复逻辑问题需要深度分析"""
    for issue in issues:
        if issue.category == "logic":
            # 分析上下文
            context = self.analyze_context(issue)
            # 生成修复
            fix = self.generate_logic_fix(context)
            # 验证修复
            if self.verify_fix(fix):
                await self.apply_fix(fix)
```

#### 3. 增强补全 (Enhance)
```python
async def enhance_completeness(self, output):
    """增强完整性"""
    # 检查缺失的处理
    if not self.has_error_handling(output):
        output = self.add_error_handling(output)
    if not self.has_edge_case_handling(output):
        output = self.add_edge_cases(output)
    return output
```

### 改进计划格式

```json
{
  "plan_id": "plan_xxx",
  "issues": [
    {
      "id": "issue_001",
      "category": "logic",
      "severity": "critical",
      "description": "空指针异常风险",
      "location": "line 42"
    }
  ],
  "changes": [
    {
      "issue_id": "issue_001",
      "type": "add_validation",
      "location": "line 40",
      "before": "data.process()",
      "after": "if data: data.process()",
      "risk": "low"
    }
  ],
  "execution_order": ["change_001", "change_002"],
  "rollback_plan": {
    "checkpoints": ["checkpoint_001"],
    "restore_command": "restore --from checkpoint_001"
  },
  "validation_plan": {
    "test_cases": ["test_001", "test_002"],
    "expected_improvement": 0.15
  }
}
```

## 迭代优化机制

### 最多5轮迭代
```python
MAX_ITERATIONS = 5

async def improve_with_iteration(self, eval_result, original):
    current = original
    history = []

    for i in range(MAX_ITERATIONS):
        # 分析当前问题
        issues = await self.analyze(current, eval_result)

        if not issues:
            break  # 没有问题，退出

        # 生成改进计划
        plan = await self.create_plan(issues)

        # 执行改进
        improved = await self.execute(plan, current)

        # 重新评估
        new_eval = await self.evaluate(improved)

        history.append({
            "iteration": i + 1,
            "improvements": plan.changes,
            "score_before": eval_result.overall_score,
            "score_after": new_eval.overall_score
        })

        if new_eval.overall_score >= 0.9:
            break  # 达到目标，退出

        current = improved
        eval_result = new_eval

    return {
        "final_result": current,
        "iterations": len(history),
        "history": history
    }
```

## 改动原则

### 最小改动原则
1. 只改必要的部分
2. 保持原有正确的逻辑
3. 避免引入新问题
4. 保持代码风格一致

### 改动优先级
| 优先级 | 问题类型 | 处理方式 |
|--------|---------|---------|
| P0 | 逻辑错误 | 立即修复 |
| P1 | 崩溃风险 | 立即修复 |
| P2 | 功能缺失 | 尽快补全 |
| P3 | 质量问题 | 逐步优化 |

## 验证改进

### 回归测试
```python
async def validate_improvements(self, improved, original):
    # 1. 确保原有功能不受影响
    regression_tests = await self.run_tests(
        tests=original.passing_tests + improved.new_tests
    )

    # 2. 确保新问题被修复
    issue_tests = await self.run_tests(
        tests=improved.issue_tests
    )

    return {
        "regression_passed": regression_tests.all_passed,
        "issues_fixed": issue_tests.all_passed,
        "overall_improvement": improved.score - original.score
    }
```

### 改动验证报告
```json
{
  "validation_id": "val_xxx",
  "iteration": 2,
  "changes_validated": 3,
  "regression_tests": {
    "total": 10,
    "passed": 10,
    "failed": 0
  },
  "issue_tests": {
    "total": 3,
    "passed": 2,
    "failed": 1
  },
  "new_issues": [],
  "overall_status": "IMPROVED"
}
```

## 与其他模式集成

### EVAL → IMPROVE → EVAL
```python
async def quality_loop(skill):
    while True:
        # 评估
        eval_result = await eval_mode.evaluate(skill)

        if eval_result.score >= 0.9:
            return skill  # 达标，退出

        # 改进
        improved = await improve_mode.improve(
            eval_result,
            skill
        )

        skill = improved.result
```

### 与Benchmark集成
```python
async def improve_against_baseline(skill, baseline):
    # 比较当前与基线
    comparison = await benchmark_mode.compare(skill, baseline)

    if comparison.relative_score < 0.8:
        # 显著低于基线，启动改进
        await improve_mode.improve_aggressive(skill)
```
