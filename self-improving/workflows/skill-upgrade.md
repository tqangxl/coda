# Hook Workflow - 定期技能升级检查

## 触发条件

- 每周日凌晨2点
- 可手动触发

## 执行流程

```yaml
workflow:
  name: "skill_upgrade_check"
  trigger: "scheduled"
  cron: "0 2 * * 0"  # 每周日凌晨2点
  namespace: "ai_agents_v2"

  steps:
    1:
      name: "analyze_effectiveness"
      description: "分析各技能的有效性"
      action: "learning.analyze_skill_effectiveness"
      timeout: 5m

    2:
      name: "compare_benchmarks"
      description: "对比基准测试结果"
      action: "benchmark.compare_with_baseline"
      timeout: 10m

    3:
      name: "generate_improvements"
      description: "生成改进建议"
      action: "skill_creator.generate_improvements"
      timeout: 5m

    4:
      name: "apply_improvements"
      description: "应用验证通过的改进"
      action: "skill_creator.apply_improvements"
      timeout: 15m

    5:
      name: "notify_result"
      description: "通知升级结果"
      action: "notification.send_upgrade_report"
      timeout: 30s
```

## SurrealDB存储

```sql
-- 技能升级记录表
DEFINE TABLE skill_upgrades SCHEMAFULL;
DEFINE FIELD id ON skill_upgrades TYPE string;
DEFINE FIELD skill_id ON skill_upgrades TYPE string;
DEFINE FIELD old_version ON skill_upgrades TYPE string;
DEFINE FIELD new_version ON skill_upgrades TYPE string;
DEFINE FIELD changes ON skill_upgrades TYPE array;
DEFINE FIELD improvement_score ON skill_upgrades TYPE float;
DEFINE FIELD executed_by ON skill_upgrades TYPE string DEFAULT 'automated';
DEFINE FIELD status ON skill_upgrades TYPE string;
DEFINE FIELD executed_at ON skill_upgrades TYPE datetime DEFAULT time::now();

-- 技能有效性分析表
DEFINE TABLE skill_effectiveness SCHEMAFULL;
DEFINE FIELD id ON skill_effectiveness TYPE string;
DEFINE FIELD skill_id ON skill_effectiveness TYPE string;
DEFINE FIELD period ON skill_effectiveness TYPE string;
DEFINE FIELD success_rate ON skill_effectiveness TYPE float;
DEFINE FIELD avg_duration ON skill_effectiveness TYPE float;
DEFINE FIELD user_satisfaction ON skill_effectiveness TYPE float;
DEFINE FIELD recommendation ON skill_effectiveness TYPE string;
DEFINE FIELD analyzed_at ON skill_effectiveness TYPE datetime DEFAULT time::now();

-- 技能基准表
DEFINE TABLE skill_benchmarks SCHEMAFULL;
DEFINE FIELD id ON skill_benchmarks TYPE string;
DEFINE FIELD skill_id ON skill_benchmarks TYPE string;
DEFINE FIELD version ON skill_benchmarks TYPE string;
DEFINE FIELD benchmark_score ON skill_benchmarks TYPE float;
DEFINE FIELD test_cases ON skill_benchmarks TYPE array;
DEFINE FIELD created_at ON skill_benchmarks TYPE datetime DEFAULT time::now();
```

## SurrealQL脚本

```sql
-- 技能有效性分析脚本
DEFINE FUNCTION fn::analyze_skill_effectiveness($period: string) {
    -- 获取该周期内的技能使用数据
    LET $skill_usage = SELECT
        skill_id,
        count() as total_uses,
        count() FILTER WHERE status = 'success' as successful,
        avg(duration) as avg_duration
    FROM skill_executions
    WHERE executed_at > time::now() - $period::duration
    GROUP BY skill_id;

    -- 计算有效性评分
    LET $effectiveness = SELECT *,
        (successful / total_uses) * 0.6 +
        (1 / (1 + avg_duration / 1000)) * 0.2 +
        0.2 as effectiveness_score
    FROM $skill_usage;

    -- 生成推荐
    FOR $skill IN $effectiveness {
        LET $recommendation = SWITCH {
            WHEN $skill.effectiveness_score >= 0.9 THEN 'excellent'
            WHEN $skill.effectiveness_score >= 0.7 THEN 'good'
            WHEN $skill.effectiveness_score >= 0.5 THEN 'needs_improvement'
            ELSE 'requires_review'
        };

        CREATE skill_effectiveness CONTENT {
            skill_id: $skill.skill_id,
            period: $period,
            success_rate: $skill.successful / $skill.total_uses,
            avg_duration: $skill.avg_duration,
            recommendation: $recommendation,
            analyzed_at: time::now()
        };
    }

    RETURN $effectiveness;
};

-- 技能改进生成脚本
DEFINE FUNCTION fn::generate_skill_improvements() {
    -- 获取需要改进的技能
    LET $needs_improvement = SELECT * FROM skill_effectiveness
        WHERE recommendation = 'needs_improvement'
        AND analyzed_at > time::now() - 7d
        ORDER BY effectiveness_score ASC
        LIMIT 5;

    -- 为每个技能生成改进建议
    LET $suggestions = [];
    FOR $skill IN $needs_improvement {
        LET $suggestion = {
            skill_id: $skill.skill_id,
            issues: (SELECT * FROM skill_executions
                WHERE skill_id = $skill.skill_id
                AND status = 'failed'
                ORDER BY executed_at DESC LIMIT 10),
            suggested_changes: [
                "优化错误处理逻辑",
                "增加边界条件检测",
                "改进响应格式化"
            ]
        };
        APPEND $suggestion TO $suggestions;
    }

    RETURN $suggestions;
};
```

## 执行示例

```python
async def weekly_skill_upgrade():
    """每周技能升级检查"""
    # 1. 分析有效性
    effectiveness = await db.query("fn::analyze_skill_effectiveness('7d')")

    # 2. 生成改进建议
    suggestions = await db.query("fn::generate_skill_improvements()")

    # 3. 应用改进
    for suggestion in suggestions:
        if suggestion["improvement_score"] >= 0.1:
            await apply_skill_upgrade(suggestion)

    # 4. 发送报告
    report = {
        "date": datetime.now().date(),
        "skills_analyzed": len(effectiveness),
        "upgrades_applied": len(applied),
        "total_improvement": sum(s["improvement_score"] for s in applied)
    }
    await send_upgrade_report(report)
```
